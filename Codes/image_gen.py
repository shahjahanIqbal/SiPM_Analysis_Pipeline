#!/usr/bin/env python3
import numpy as np
import h5py
from pathlib import Path
import logging
from scipy.signal import savgol_filter
import matplotlib.pyplot as plt
from matplotlib.offsetbox import AnchoredText
import numpy as np
import tifffile as tiff
from config_loader import load_config
from geometry import CameraLayout
from tqdm import tqdm

import os

os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"
config = load_config("config/config.yaml")

# Plot colors 
BG = "#ffffff"
PLOT1 = "#236E62"
PLOT1_SEC = "#97F3B1"
PLOT2 = "#0067ae"
PLOT3 = "#e77e51"
VLINE1 = "#ffa17a"
VLINE2 = "#43658d"
VLINE3 = "#213245"
TEXT = "#232324"
BOX_BG = "#afccc6"
GRID = "#c0cdd4"

offset_filepath = Path(config["calib"]["drsoffset"])
#adc_data_path = Path("output/s0534+2201_339_flashCAL_14122025_2_EVBdata.h5")

# Validate file paths for DRS Offsets and ADC data

if not offset_filepath.exists():
    #logging.error(f"DRS OFFSET file missing! Please ensure the offset correction files are present in the directory {offset_filepath}")
    #exit
    raise FileNotFoundError(f"DRS offset file missing: {offset_filepath}")


def gaussianFunction(x,  sigma = 5): # Width of a Cherenkov pulse is typically around 25 ns
    ''' 
        Input: x (1D array), sigma (float, default 5)
        Output: 1D array, normalised Gaussian kernel
        Evaluates exp(-0.5*(x/sigma)^2) over the input array and divides by its sum.
        The result is used as the convolution kernel in peakFinder. The default sigma
        of 5 samples corresponds roughly to the expected width of a Cherenkov pulse.
    '''
    gauss = np.exp( - 0.5 * (x / sigma)**2)
    return gauss / np.sum(gauss)


#-----------------------------|Define Gaussian Globally|-------------------------------#
KERNEL_X = np.arange(-35,36, 1)
GAUSS = gaussianFunction(KERNEL_X) 
                                   


def peakFinder(adc, kernel = GAUSS):
    '''
        Input: adc (1D array), kernel (1D array, default module-level GAUSS)
        Output: int, sample index of the detected pulse peak
        Smooths the raw ADC trace with a Savitzky-Golay filter (window 9, order 3),
        then convolves with the Gaussian kernel. Returns the argmax of the convolution
        result. Used to locate the integration window for both HG and LG channels.

    '''
    # Smoothing
    
    smooth_pulse = savgol_filter(adc, 9, 3) # Can these parameters be optimized?
                                                                      
    # Convolution
    # Peak must be searched within a buffer window of size >= width of the convolving function
    # The zero padding in the convolution results in peaks near the start and end
    conv = np.convolve(kernel, smooth_pulse, mode = 'same')
    peak_pos = np.argmax(conv)

    
    return peak_pos



def adcTomV(adc, cstop, skip_cell, offsets, peak_pos = None): 
    '''
        Input: adc (1D int array), cstop (int), skip_cell (int),
               offsets (1D float array or None), peak_pos (int, optional)
        Output: tuple (pulse_mV, roi_x, arrival_time, start, end, saturation_flag)
        Channel-wise conversion of adc data t0 mV.
        Converts raw ADC counts to mV using a 14-bit full-scale of 1000 mV. Applies
        per-capacitor DRS offset correction by cycling through offsets with (roi_x +
        cstop) % 1024. Computes and subtracts a baseline from samples outside a window
        of half-length 12 around the peak. Sets saturation_flag if any sample within
        the window exceeds 1000 mV. If peak_pos is not supplied it is found internally
        via peakFinder.
        peak_pos is None by default. This is to account for the possible lack of any detectable pulse in the LG channel.
        The peak is calculated for HG channel regardless of saturation as the convolution is capable of estimating the peak
        The same peak will be passed as the input parameter for the LG channel conversion.
    '''
    #ADC to mV and ROI to capacitor index conversion       
    if peak_pos is None:
        peak_pos = peakFinder(adc)

    roi_x = np.arange(0, np.size(adc), 1)
    whl = 12 # window half length
    start = max(0, peak_pos - whl)
    end = min(len(adc), peak_pos + whl)
    
    baseline_mask = (roi_x < start) | (roi_x > end) #)
    #peak_y = adc 
    #peak_x = roi_x 
    
    pulse_mV = ((1000 / 16384) * adc)   

    # DRS offset correction

    # Check for saturation
    saturation_flag = False
    if np.any(pulse_mV[start:end] > 1000): 
        saturation_flag = True
   
    time = (roi_x + cstop) # + skip_cell ) 
    
    arrival_time = peak_pos  


    for i, t in enumerate(time):
            pulse_mV[i] = pulse_mV[i] + offsets[t%1024] if offsets is not None else pulse_mV[i]
    if np.any(baseline_mask):
        baseline_corr = np.median(pulse_mV[baseline_mask])
    else:
        baseline_corr = 0
                                                                                                    
    pulse_mV -= baseline_corr

    return (pulse_mV, roi_x, arrival_time, start, end, saturation_flag)




def chargePerPixel(peak_x, peak_y, start, end):
    '''
        Input: peak_x (1D array of sample indices), peak_y (1D mV array),
               start (int), end (int) — integration window boundaries
        Output: float, integrated charge in pC

        The pulse, ROI values, and pulse start and end positions are the input parameters
        Applies a Savitzky-Golay smooth to peak_y, slices to the [start, end] window to 
        remove noise before integration.
        The pulse is integrated within the window using the trapezoidal rule to compute the charge.
        Divides by 50 ohm to convert mV sample to pC, assuming 1 GHz sampling rate (1 sample = 1 ns).
    '''
    # Smoothing to reduce noise before integration
    smooth_peak = savgol_filter(peak_y, 9, 3) 
    peak_y = smooth_peak[start:end] #mV 
    peak_x = peak_x[start:end]  #ns 
    charge = np.trapezoid(peak_y, peak_x) / 50
    return charge 



def edgeDetector(ref_pulse_mv, peak_pos, window=20, thr_frac=0.4):
    '''
        Input: ref_pulse_mv (1D mV array), peak_pos (int),
               window (int, default 20), thr_frac (float, default 0.4)
        Output: int, sample index of the rising edge
        Scans backward from peak_pos within the given window looking for three
        consecutive samples that cross the threshold (peak amplitude * thr_frac) from
        below. Returns the crossing index, or peak_pos if none is found. Used to
        correct arrival times relative to the reference channel edge.
    '''

    peak_mv = ref_pulse_mv[peak_pos]
    threshold = peak_mv * thr_frac

    start = max(0, peak_pos - window)

    for i in range(start, peak_pos-2):

        if (
            ref_pulse_mv[i] < threshold and
            ref_pulse_mv[i+1] >= threshold and
            ref_pulse_mv[i+2] > threshold  
        ):
            return i+1

    return peak_pos

def imageGen(roi_data, cstop, skip_cell, offsets, geometry):
    '''
        Input: roi_data (2D int16 array, N_GLOBAL_CH x ROI), cstop (1D array),
               skip_cell (1D array), offsets (2D float array), geometry (CameraLayout)
        Output: (charge_image, time_image, saturation_mask) — three 1D float arrays
                of length N_GLOBAL_CH
        Iterates over all DDB blocks. For each block it reads the reference channel
        and detects its rising edge for timing correction. It then processes each
        LG/HG pixel pair: calls adcTomV for both gains, chargePerPixel for charge,
        and records arrival times relative to the reference edge. Returns flat arrays
        that are subsequently passed to mapToPixels.
    '''

    charge_image = np.zeros(geometry.N_GLOBAL_CH)
    time_image = np.zeros(geometry.N_GLOBAL_CH)
    saturation_mask = np.zeros(geometry.N_GLOBAL_CH) #Dont really need masks for LG Channels. Will optimize later
    
    for gch in range(0, geometry.N_GLOBAL_CH, geometry.N_CH_PER_DDB):
                
        ref_data = roi_data[gch + geometry.N_CH_PER_DDB - 1]

        ref_data_mv, _, arrival_time_ref, _, _,_ = adcTomV(ref_data, 0, 0, None)
        ref_time = edgeDetector(ref_data_mv, arrival_time_ref)
        block_size = 1024

        for i in range(1, geometry.N_CH_PER_DDB - 1, 2):
             
            adc_pulse_hg = roi_data[gch + i]
            adc_pulse_lg = roi_data[gch + i - 1]
            cstop_val_hg = cstop[gch + i]
            cstop_val_lg = cstop[gch + i - 1]
            skip_cell_val_hg = skip_cell[gch + i]
            skip_cell_val_lg = skip_cell[gch + i - 1]
             
            block_size = 1024

            # If HG is not saturated, use it for charge calculation
            lch_id_hg, ddb_id_hg, pcm_id_hg = geometry.local_channel_id(gch + i)
            lch_id_lg, ddb_id_lg, pcm_id_lg = geometry.local_channel_id(gch + i - 1) 
            
            drs_offset_time_hg = block_size * (pcm_id_hg * geometry.N_DDB + ddb_id_hg)
            drs_offset_time_lg = block_size * (pcm_id_lg * geometry.N_DDB + ddb_id_lg)
            drs_offset_slice_hg = offsets[drs_offset_time_hg: drs_offset_time_hg + block_size, lch_id_hg + 1] # +1 because first column DRS capacitor index
            drs_offset_slice_lg = offsets[drs_offset_time_lg: drs_offset_time_lg + block_size, lch_id_lg + 1]
            
            peak_pos = peakFinder(adc_pulse_hg)
            pulse_hg, time, arrival_time_hg, start, end, sat_flag_hg = adcTomV(adc_pulse_hg, cstop_val_hg, skip_cell_val_hg, drs_offset_slice_hg)
            pulse_lg, time, arrival_time_lg, start, end, sat_flag_lg = adcTomV(adc_pulse_lg, cstop_val_lg, skip_cell_val_lg, drs_offset_slice_lg, peak_pos)
            
            charge_hg = chargePerPixel(time, pulse_hg, start, end)
            charge_lg = chargePerPixel(time, pulse_lg, start, end)
            charge_image[gch + i] = charge_hg
            charge_image[gch + i - 1] = charge_lg
            time_image[gch + i] = arrival_time_hg
            time_image[gch + i - 1] = arrival_time_lg

            saturation_mask[gch + i] = sat_flag_hg
            saturation_mask[gch + i - 1] = sat_flag_lg
            
        time_image[gch:gch+geometry.N_CH_PER_DDB] =np.abs(time_image[gch:gch+geometry.N_CH_PER_DDB] -  ref_time)

    return charge_image, time_image, saturation_mask

def plotReferencePulses(event_id, roi_data, geometry, output_dir):
    '''
        Input: event_id (int), roi_data (2D array), geometry (CameraLayout),
               output_dir (Path)
        Output: none; saves PNG files to output_dir/ref_pulses/Event_{event_id}/
        For each DDB, extracts the reference channel waveform, converts to mV, runs
        peakFinder and edgeDetector, and plots the waveform with the detected edge
        marked as a scatter point. Intended for debugging timing corrections.
    '''

    ref_dir = output_dir / "ref_pulses" / f"Event_{event_id}"
    ref_dir.mkdir(parents=True, exist_ok=True)

    for gch in range(0, geometry.N_GLOBAL_CH, geometry.N_CH_PER_DDB):

        ref_ch = gch + geometry.N_CH_PER_DDB - 1
        ref_pulse = roi_data[ref_ch]
        peak_pos = peakFinder(ref_pulse)
        
        edge = edgeDetector(ref_pulse, peak_pos)
        ref_pulse, _, _, _, _,_ = adcTomV(roi_data[ref_ch], cstop=0, skip_cell=0, offsets=None)
        x = np.arange(len(ref_pulse))
        

        fig, ax = plt.subplots(figsize=(8,5), dpi=150)
        fig.patch.set_facecolor(BG)
        

        ax.plot(x, ref_pulse, "o--", label="Reference Pulse", color = PLOT1, zorder = 1)


        ax.scatter(edge,
                   ref_pulse[edge],
                   color=PLOT3,
                   s=80,
                   label="Detected Edge",
                   zorder = 2)

        ax.set_title(f"Event {event_id}  |  Ref Channel {ref_ch}",  fontweight='bold',)
        ax.set_xlabel("Sample",  fontweight='bold',)
        ax.set_ylabel("ADC", fontweight='bold',)

        ax.legend(
            edgecolor = GRID,
            loc = "upper right",
            prop = {'weight': 'bold', 'size': 10},
            handlelength = 1.5,
            framealpha   = 0.6,)
        ax.grid()

        fname = ref_dir / f"refch_{ref_ch}.png"
        fname.parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(fname)
        plt.close()


def mapToPixels(geometry, image, pixel_map, gch):
    '''
        Input: geometry (CameraLayout), image (1D array), pixel_map (2D int array),
               gch (1D int array of global channel indices)
        Output: (image_LG, image_HG) — two 2D float arrays matching pixel_map shape
        Masks out reference channels (every N_CH_PER_DDB-th channel), then separates
        the remaining values into even-indexed (LG) and odd-indexed (HG) arrays.
        Uses pixel_map as an index array to reorder channels into their physical
        camera positions.
    '''
    mask = (gch % geometry.N_CH_PER_DDB != geometry.N_CH_PER_DDB - 1)

    pixel_map = pixel_map.astype(int)

    imaging_mask = image[mask]
    LG = imaging_mask[0::2]
    HG = imaging_mask[1::2]
    image_LG = LG[pixel_map]
    image_HG = HG[pixel_map]
    
    return image_LG, image_HG


def saveImage(event_id, image, cmap = 'viridis'):
    '''
    Saves a compressed image for quick inspection
    '''
    colormap = plt.get_cmap(cmap)
    rgba = colormap(image)   
    rgb = (rgba[:, :, :3] * 255).astype("uint8")

    tiff.imwrite(Path(event_id).with_suffix(".tiff"), rgb, compression="deflate")

def saveImageHiRes(event_id, label, image, output_dir, pixel_map, geometry, cmap='viridis'):
    '''
        Input: event_id (str), label (str), image (2D array), output_dir (Path),
               pixel_map (2D int array), geometry (CameraLayout), cmap (str)
        Output: none; saves a PNG to output_dir/{label}/{event_id}.png
        Renders the camera image with matplotlib imshow at 300 DPI. Overlays each
        pixel's ID and its LG/HG global channel index pair as small text annotations.
        A colorbar is added with the provided label. The output subdirectory is
        created if absent.

        Optionally charge or time values can also be displayed by uncommenting the specific code block
        label specifies if its a charge image or arrival time image
    '''
    fig, ax = plt.subplots(figsize=(8, 8), dpi=300)
    
    im = ax.imshow(image, cmap=cmap)
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label(label)
    rows, cols = image.shape

    glob_ch_indices = np.arange(0, geometry.N_GLOBAL_CH, 1)
    mask = (glob_ch_indices % geometry.N_CH_PER_DDB != geometry.N_CH_PER_DDB - 1)
    glob_ch_indices = glob_ch_indices[mask]
    lg_glob = glob_ch_indices[0::2]
    for i in range(rows):
        for j in range(cols):

            pix_id = int(pixel_map[i, j])

            ax.text(
                j, i,
                str(pix_id),
                ha='center',
                va='bottom',   
                fontsize=6,
                color='white'
            )
            ax.text(
                j, i,
                str(f"({lg_glob[pix_id]}, {lg_glob[pix_id]+1})"),
                ha='center',
                va='top',
                fontsize=4,
                color='white'
            )

            #charge = image[i, j]

            #ax.text(
            #    j, i,
            #    f"{charge:.1f}",
            #    ha='center',
            #    va='top',
            #    fontsize=3,
            #    color='white'
            #)

    ax.set_title(f"Event {event_id.replace('_', ' ' )}")
    ax.set_xticks([])
    ax.set_yticks([])

    output_path = output_dir /f"{label.replace(' ', '_')}"/ f"{event_id}.png"
    output_path.parent.mkdir(parents = True, exist_ok=True)
    plt.savefig(output_path, bbox_inches='tight')
    plt.close(fig)

def chargeDist(event_id, image, label, xlabel, output_dir, charge_flag=False):
    '''
        Input: event_id (int), image (2D array), label (str), xlabel (str),
               output_dir (Path), charge_flag (bool, default False)
        Output: none; saves a PNG to output_dir/Dist/
        Flattens the image and plots a histogram with auto bin count. When
        charge_flag is True, adds a vertical mean line and a shaded region marking
        the 6*MAD picture threshold. Summary statistics (mean, std, MAD, min, max)
        are shown in the legend as blank-handle entries.
    '''
    with plt.style.context('seaborn-v0_8-whitegrid'):

        N = 6

        fig, ax = plt.subplots(figsize=(9, 6), dpi=300)
        fig.patch.set_facecolor(BG)
        

        image    = image.flatten()
        mean_val = np.mean(image)
        std_val  = np.std(image)
        min_val  = np.min(image)
        max_val  = np.max(image)
        med_val  = np.median(image)
        mad_val  = np.median(np.abs(image - med_val))

        ax.hist(image, bins='auto', color=PLOT1, linewidth=0.4,
                edgecolor=PLOT1_SEC, alpha=0.8, zorder=2)

        if charge_flag:
            threshold = N * mad_val
            ax.axvline(mean_val, color=VLINE1, linestyle="--", linewidth=1.6, label=f"Mean", zorder=3)
            ax.axvspan(0, threshold, alpha=0.15, color=VLINE2,label=f"Picture Threshold {N}·MAD", zorder=1)
            ax.axvline(threshold, color=VLINE2, linestyle=":", linewidth=1.2, zorder=3)
            ax.axvline(0, color=VLINE2, linestyle=":", linewidth=1.2, zorder=3)
            #ax.axvline(mad_val, color=VLINE3, linewidth=2, linestyle="--", label="MAD")

        ax.grid(axis="y", color=GRID, linewidth=0.6, zorder=0)
        ax.grid(axis="x", color=GRID, linewidth=0.4, linestyle=":", zorder=0)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)

        ax.set_xlabel(xlabel, fontsize=12, fontweight='bold')
        ax.set_ylabel("Counts", fontsize=12, fontweight='bold')
        ax.set_title(label, fontsize=14, fontweight='bold', pad=12)

        from matplotlib.patches import Patch
        blank = Patch(visible=False)

        handles, labels = ax.get_legend_handles_labels()

        divider = " " * 22 if charge_flag else ""
        extra_labels = [
            divider,
            f"Mean = {mean_val:.2f}",
            f"Std  = {std_val:.2f}",
            f"MAD  = {mad_val:.2f}",
            f"Min  = {min_val:.2f}",
            f"Max  = {max_val:.2f}",
        ]
        handles += [blank] * len(extra_labels)
        labels  += extra_labels

        legend = ax.legend(
            handles, labels,
            edgecolor    = GRID,
            loc          = "upper right",
            prop         = {'weight': 'bold', 'size': 10},
            handlelength = 1.5,
            framealpha   = 0.9,
        )
        legend.get_frame().set_linewidth(0.8)
        for text in legend.get_texts():
            text.set_color(TEXT)

        charge_dir = output_dir / "Dist"
        charge_dir.mkdir(parents=True, exist_ok=True)
        output_path = charge_dir / f"{event_id}_{label.replace(' ', '_')}.png"
        plt.tight_layout()
        plt.savefig(output_path, bbox_inches='tight',
                    facecolor=fig.get_facecolor())
        plt.close(fig)

# PLOT THE PULSES

def plotLGHGPulseWithWindow(roi_data, cstop, offsets, skip_cell, geometry, global_ch, event_index, output_dir):
    
    """
        Input: roi_data (2D array), cstop (1D array), offsets (2D array),
               skip_cell (1D array), geometry (CameraLayout), global_ch (int),
               event_index (int), output_dir (Path)
        Output: none; saves a PNG to output_dir/Event_{event_index}/ as {pcm}_{ddb}_{ch}.png
        Extracts and converts the LG and HG waveforms for a single pixel pair using
        adcTomV. If HG is saturated the peak is found independently for each gain;
        otherwise the HG peak is reused for LG. Plots both waveforms with integration
        window markers and per-gain baseline mean lines.
    """

    lch_id, ddb_id, pcm_id = geometry.local_channel_id(global_ch)

    # LG is even channel, HG is odd channel
    hg_ch = global_ch
    lg_ch = hg_ch - 1
    
    block_size = 1024
       
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    fig.patch.set_facecolor(BG)
    
    adc_pulse_lg = roi_data[lg_ch]
    cstop_val_lg = cstop[lg_ch]
    skip_cell_val_lg = skip_cell[lg_ch]

    lch_id_lg, ddb_id_lg, pcm_id_lg = geometry.local_channel_id(lg_ch)
    drs_offset_time_lg = block_size * (pcm_id_lg * geometry.N_DDB + ddb_id_lg)
    drs_offset_slice_lg = offsets[drs_offset_time_lg: drs_offset_time_lg + block_size, lch_id_lg + 1]  
    
    adc_pulse_hg = roi_data[hg_ch]
    cstop_val_hg = cstop[hg_ch]
    skip_cell_val_hg = skip_cell[hg_ch]

    lch_id_hg, ddb_id_hg, pcm_id_hg = geometry.local_channel_id(hg_ch)
    drs_offset_time_hg = block_size * (pcm_id_hg * geometry.N_DDB + ddb_id_hg)
    drs_offset_slice_hg = offsets[drs_offset_time_hg: drs_offset_time_hg + block_size, lch_id_hg + 1]
    
    if np.any(adc_pulse_hg >= 16383):
        pulse_lg, time_lg, arrival_time_lg, start_lg, end_lg,_ = adcTomV(adc_pulse_lg, cstop_val_lg, skip_cell_val_lg, drs_offset_slice_lg)
        pulse_hg, time_hg, arrival_time_hg, start_hg, end_hg,_ = adcTomV(adc_pulse_hg, cstop_val_hg, skip_cell_val_hg, drs_offset_slice_hg)
    else:
        hg_peak = peakFinder(adc_pulse_hg)
        pulse_lg, time_lg, arrival_time_lg, start_lg, end_lg,_ = adcTomV(adc_pulse_lg, cstop_val_lg, skip_cell_val_lg, drs_offset_slice_lg, peak_pos = hg_peak)
        pulse_hg, time_hg, arrival_time_hg, start_hg, end_hg,_ = adcTomV(adc_pulse_hg, cstop_val_hg, skip_cell_val_hg, drs_offset_slice_hg, peak_pos = hg_peak)
    
    # Plot waveform
    ax.plot(time_lg, pulse_lg, label=f"LG Ch {lch_id_lg}", color = PLOT1)

    ax.plot(time_hg, pulse_hg, label=f"HG Ch {lch_id_hg}", color = PLOT3)

    roi_len = len(time_lg)
    ax.axvline(time_lg[min(start_hg, roi_len - 1)], linestyle="--", color=VLINE1,  alpha=0.8)
    ax.axvline(time_lg[min(end_hg,   roi_len - 1)], linestyle="--", color=VLINE1,  alpha=0.8)
    ax.axvline(time_lg[min(start_lg, roi_len - 1)], linestyle="--", color= VLINE2, alpha=0.8)
    ax.axvline(time_lg[min(end_lg,   roi_len - 1)], linestyle="--", color= VLINE2, alpha=0.8)
    mask_lg = (time_lg < time_lg[min(start_hg, roi_len - 1)]) | (time_lg > time_lg[min(end_hg,   roi_len - 1)])
    mask_hg = (time_hg < time_hg[min(start_hg, roi_len - 1)]) | (time_hg > time_hg[min(end_hg,   roi_len - 1)])
    #ax.axhline(np.median(pulse_lg[mask_lg]), linestyle=":", color=PLOT1, alpha=0.7, label = f"Baseline Median")
    #ax.axhline(np.median(pulse_hg[mask_hg]), linestyle=":", color=PLOT3, alpha=0.7, label = f"Baseline Median")
    ax.axhline(np.mean(pulse_lg[mask_lg]), linestyle="--", color=PLOT1, alpha=0.7, label = f"Baseline Mean")
    ax.axhline(np.mean(pulse_hg[mask_hg]), linestyle="--", color=PLOT3, alpha=0.7, label = f"Baseline Mean")

    ax.set_xlabel("ROI", fontweight='bold')
    ax.set_ylabel("Amplitude (mV)",  fontweight='bold')
    ax.set_title(f"PCM {pcm_id} | DDB {ddb_id}", fontweight='bold',)
    ax.legend( 
            edgecolor    = GRID,
            loc          = "upper right",
            prop         = {'weight': 'bold', 'size': 10},
            handlelength = 1.5,
            framealpha   = 0.6,
            )
    
    ax.grid(True)

    filename = f"pcm{pcm_id}_ddb{ddb_id}_ch{lch_id_lg}_{lch_id_hg}.png"
    pulse_dir = output_dir / f"Event_{event_index}"
    pulse_dir.mkdir(parents=True, exist_ok=True)
    output_path = pulse_dir / filename
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close(fig)

def plotAllPulses(roi_data, cstop, offsets, skip_cell, geometry, event_index, output_dir):
    """
        Input: roi_data (2D array), cstop (1D array), offsets (2D array),
               skip_cell (1D array), geometry (CameraLayout), event_index (int),
               output_dir (Path)
        Output: none; calls plotLGHGPulseWithWindow for every HG channel in the event
        Iterates over every DDB block and every HG channel within each block (odd
        local channel indices from 1 to N_CH_PER_DDB - 2). Generates one plot per
        LG/HG pair. Large output volume; intended for detailed per-event diagnosis.
    """
 
    for ddb_start in range(0, geometry.N_GLOBAL_CH, geometry.N_CH_PER_DDB):
        for i in range(1, geometry.N_CH_PER_DDB - 1, 2):   
            hg_global_ch = ddb_start + i
            plotLGHGPulseWithWindow(roi_data,cstop, offsets, skip_cell, geometry, hg_global_ch, event_index, output_dir)

def saveImages(event_index, roi_slice, cstop_slice, skip_cell_slice, offsets, geometry, pixel_map, gch, output_dir):
    '''
        Input: event_index (int), roi_slice (2D array), cstop_slice (1D array),
               skip_cell_slice (1D array), offsets (2D array), geometry (CameraLayout),
               pixel_map (2D int array), gch (1D int array), output_dir (Path)
        Output: tuple (ch_image_LG, ch_image_HG, t_image_LG, t_image_HG)
        Thin wrapper that calls imageGen followed by mapToPixels for both charge and
        time arrays. Returns all four 2D image arrays. Does not save any files itself.

        It's noted that the event_index and output_dir are not utilized within this function but I've chosen to 
        stick to the old adage "If it ain't broke, don't fix it" for now to avoid unintended consequences in the main processing loop.
    '''
    charge_image, time_image, _ = imageGen(roi_slice, cstop_slice, skip_cell_slice, offsets, geometry)
    
    ch_image_LG, ch_image_HG = mapToPixels(geometry, charge_image, pixel_map, gch)
    t_image_LG, t_image_HG = mapToPixels(geometry, time_image, pixel_map, gch)
    return ch_image_LG, ch_image_HG, t_image_LG, t_image_HG


def processEvent(event_index, roi_slice, cstop_slice, skip_cell_slice, offsets, geometry, pixel_map, gch, output_dir):
    '''
        Input: event_index (int), roi_slice (2D array), cstop_slice (1D array),
               skip_cell_slice (1D array), offsets (2D array), geometry (CameraLayout),
               pixel_map (2D int array), gch (1D int array), output_dir (Path or None)
        Output: dict with keys event_id, image_LG, image_HG, time_HG, saturation_mask
        The primary worker function used throughout the parallel pipelines. Calls
        imageGen, then mapToPixels for charge, time, and the saturation mask. Returns
        the results as a dict; output_dir is accepted but not used in the current
        implementation (kept for API consistency).

        Again, output_dir is not used. Refer to adage mentioned in saveImages.
    '''

    charge_image, time_image, sat_mask = imageGen(roi_slice, cstop_slice, skip_cell_slice, offsets, geometry)
    
    ch_image_LG, ch_image_HG = mapToPixels(geometry, charge_image, pixel_map, gch)
    _, t_image_HG = mapToPixels(geometry, time_image, pixel_map, gch)
    _, satmask_HG = mapToPixels(geometry, sat_mask, pixel_map, gch)
    
    # Save preview only (raw save if needed)
    #saveImage(f"{output_dir}/{event_index}_LG", image_LG)
    #saveImage(f"{output_dir}/{event_index}_HG", image_HG)

    return {
            "event_id": event_index,
            "image_LG": ch_image_LG,
            "image_HG": ch_image_HG,
            #"time_LG": t_image_LG,
            "time_HG": t_image_HG,
            "saturation_mask": satmask_HG
            }       
    
