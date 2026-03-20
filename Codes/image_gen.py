#!/usr/bin/env python3
import numpy as np
#import traceback
import h5py
from pathlib import Path
import logging
from scipy.signal import savgol_filter
import matplotlib.pyplot as plt
import numpy as np
import tifffile as tiff
from config_loader import load_config
from geometry import CameraLayout
#from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
import cmyt

import os
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"
config = load_config("config/config.yaml")
#offset_filepath = Path("../DRS_OFFSET/all_cdm_ddb_drsoffsets_fro_09112024_1.cofsm")
#offset_filepath = Path("../DRS_OFFSET/offsetcal_January13012026.txt")
offset_filepath = Path(config["calib"]["drsoffset"])
adc_data_path = Path("output/s0534+2201_339_flashCAL_14122025_2_EVBdata.h5")

# Validate file paths for DRS Offsets and ADC data

if not offset_filepath.exists():
    logging.error(f"DRS OFFSET file missing! Please ensure the offset correction files are present in the directory {offset_filepath}")
    exit

elif not adc_data_path.exists():
    logging.error(f"Output file not found in the directory {adc_data_path}. Make sure the event extraction is done first or check the directory path")
    exit



#---------------------------------------------|Gaussian Function|---------------------------------------------#
def gaussianFunction(x,  sigma = 5): # Width of a Cherenkov pulse is typically around 25 ns
    gauss = np.exp( - 0.5 * (x / sigma)**2)
    return gauss / np.sum(gauss)


#-----------------------------|Define Gaussian Globally|-------------------------------#
KERNEL_X = np.arange(-35,36, 1)
GAUSS = gaussianFunction(KERNEL_X) 
                                   

#---------------------------------------------|Peak Fitting|---------------------------------------------#
def peakFinder(adc, kernel = GAUSS):
    # Smoothing
    
    smooth_pulse = savgol_filter(adc, 9, 3) # REASONING BEHIND THESE VALUES??
                                                                      
    # Convolution
    # Peak must be searched within a buffer window of size >= width of the convolving function
    # The zero padding in the convolution results in peaks near the start and end
    conv = np.convolve(kernel, smooth_pulse, mode = 'same')
    peak_pos = np.argmax(conv)
    #print(f"peakPos= {peak_pos}")
    
    return peak_pos


#---------------------------------------------|ADC to mV Conversion|---------------------------------------------#
def adcTomV(adc, cstop, skip_cell, offsets, peak_pos = None): # offsets must be sliced from the original file specifically for the channel              
                                                              # peak_pos parameter will be None for HG and calculated, the same will be used for LG
    '''
    Channel-wise conversion of adc data t0 mV. 
    The ADC data, skip_cell, cstop and offsets for each channel is input 
    peak_pos is None by default. This is to account for the possible lack of any detectable pulse in the LG channel.
    The peak is calculated for HG channel regardless of saturation as the convolution is capable of estimating the peak
    The same peak will be passed as the input parameter for the LG channel conversion
    '''
    #ADC to mV and ROI to time conversion       
    if peak_pos is None:
        peak_pos = peakFinder(adc)

    roi_x = np.arange(0, np.size(adc), 1)
    whl = 12 # window half length
    start = max(0, peak_pos - whl)
    end = min(len(adc), peak_pos + whl)
    
    baseline_mask = (roi_x < start) | (roi_x > end) #roi_x[~np.isin(roi_x, list(range(start, end)))]
    #baseline_corr = np.mean(adc[baseline_mask]) if len(baseline_mask) > 0 else 0
    
    #adc = adc - baseline_corr
    #print(f"Baseline correction mean {np.mean(adc[baseline_mask])}, median {np.median(adc[baseline_mask])}")
    peak_y = adc #[start : end]
    peak_x = roi_x #[start : end]
    #pulse_mV = (((1000 / 16384) * peak_y) - 500)  #if np.sum(peak_y) > 0 else np.zeros_like(peak_y)
    pulse_mV = ((1000 / 16384) * peak_y)   #if np.sum(peak_y) > 0 else np.zeros_like(peak_y)
    #baseline_corr = np.median(pulse_mV[baseline_mask]) if len(baseline_mask) > 0 else 0
    #print(f"Pulse mv: {pulse_mV}")
    #print(f"Baseline correction mean (mV) {np.mean(pulse_mV[baseline_mask])}, median {np.median(pulse_mV[baseline_mask])}")
    #print(f"Baseline correction: {1000 / 16384 * baseline_corr}")S
    # DRS offset correction
    saturation_flag = False
    if np.any(pulse_mV[start:end] > 1000): #Check for saturation
        saturation_flag = True
    #cstop = 980
    time = (peak_x + cstop) # + skip_cell ) 
    
    arrival_time = peak_pos  
    # If the pulse is zero (invalid pixel or event) return 0 and not offset values. 
    # Without this condition, if no pulse is recorded, the integrated charge of the offset voltage within the window is returned
    


    #if np.any(pulse_mV > 0): #REMOVE THIS CONDITION
    #for i, t in enumerate(time):
    #    pulse_mV[i] = pulse_mV[i] - offsets[t%1024] if offsets is not None else pulse_mV[i]
    #    #pulse_mV = pulse_mV - offsets[(peak_x + cstop + skip_cell) % 1024] if offsets is not None else pulse_mV
    #else:
    # pulse_mV = np.zeros_like(pulse_mV) 

    

    for i, t in enumerate(time):
            pulse_mV[i] = pulse_mV[i] + offsets[t%1024] if offsets is not None else pulse_mV[i]
    if np.any(baseline_mask):
        baseline_corr = np.median(pulse_mV[baseline_mask])
    else:
        baseline_corr = 0
                                                                                                    
    #baseline_corr = np.median(pulse_mV[baseline_mask]) if len(baseline_mask) > 0 else 0
    pulse_mV -= baseline_corr
    #print(f"Pulse: {pulse_mV}")
    return (pulse_mV, time, arrival_time, start, end, saturation_flag)



def chargePerPixel(peak_x, peak_y, start, end):
    '''
    The pulse, ROI values, and pulse start and end positions are the input parameters
    The pulse is smoothened with a savgol filter to remove noise before integration
    start and end positions are used to define the pulse window
    The pulse is integrated within the window to compute the charge.
    Resistance is 50ohm
    '''
    #print(f"peaky before smoothing {peak_y}")
    smooth_peak = savgol_filter(peak_y, 9, 3) #sSmoothing to reduce noise before integration
    #print(f"peaky after smoothing: {smooth_peak}")
    peak_y = smooth_peak[start:end] #mV 
    peak_x = peak_x[start:end]  #ns 
    #print(f"Peakx = {peak_x}, peaky = {peak_y}")
    charge = np.trapezoid(peak_y, peak_x) / 50

    #print(f"Charge: {charge}")
    return charge #if charge >= 0 else 0 # Some LG channels oscillate around 0. Set charge to 0 if pulse interation returns negative





'''def edgeDetector(ref_pulse_mv, peak_pos, window=20, thr_offset=0.9):
    


    peak_mv = ref_pulse_mv[peak_pos]
    threshold = peak_mv * thr_offset

    start = max(0, peak_pos - window)

    for i in range(start, peak_pos-2):

        if (
            ref_pulse_mv[i]   >= threshold and
            ref_pulse_mv[i+1] >= threshold and
            ref_pulse_mv[i+2] >= threshold
        ):
            return i

    # fallback if not found
    return peak_pos'''

def edgeDetector(ref_pulse_mv, peak_pos, window=20, thr_frac=0.4):

    '''
    Detects the rising edge of the reference pulse
    Used to correct the delay in the arrival time computation
    '''

    peak_mv = ref_pulse_mv[peak_pos]
    threshold = peak_mv * thr_frac

    start = max(0, peak_pos - window)

    for i in range(start, peak_pos-2):

        if (
            ref_pulse_mv[i] < threshold and
            ref_pulse_mv[i+1] >= threshold and
            ref_pulse_mv[i+2] > threshold  #ref_pulse_mv[i+2]
        ):
            return i+1

    return peak_pos

def imageGen(roi_data, cstop, skip_cell, offsets, geometry):

    '''
    Computes the LG and HG charge and the corrected pulse arrival time for each pixel
    Returns the Charge and Arrival Time data for each channel which will be used to generate the LG, HG and Arrival Time images
    '''
    
    #mask = (glob_ch_indices % geometry.N_CH_PER_DDB != geometry.N_CH_PER_DDB - 1)
    #glob_ch_indices = glob_ch_indices[mask]
    #glob_ref_ch_indices = glob_ch_indices[~mask]
    
    charge_image = np.zeros(geometry.N_GLOBAL_CH)
    time_image = np.zeros(geometry.N_GLOBAL_CH)
    saturation_mask = np.zeros(geometry.N_GLOBAL_CH) #Dont really need masks for LG Channels. Will optimize later
    
    for gch in range(0, geometry.N_GLOBAL_CH, geometry.N_CH_PER_DDB):
                
        ref_data = roi_data[gch + geometry.N_CH_PER_DDB - 1]
        #arrival_time_ref = peakFinder(ref_data)
        #ref_time = arrival_time_ref
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
    Plots all the reference channel pulse for an event along with the detected edge position
    Used for debugging purposes
    '''

    ref_dir = output_dir / "ref_pulses"
    ref_dir.mkdir(parents=True, exist_ok=True)

    for gch in range(0, geometry.N_GLOBAL_CH, geometry.N_CH_PER_DDB):

        ref_ch = gch + geometry.N_CH_PER_DDB - 1
        ref_pulse = roi_data[ref_ch]
        peak_pos = peakFinder(ref_pulse)
        #print(f"len ={len(ref_pulse)}, peak = {peak_pos}")

        #print(f"lenmv ={len(ref_pulse)}, peak = {peak_pos}")
        # same logic as imageGen
        
        edge = edgeDetector(ref_pulse, peak_pos)
        ref_pulse, _, _, _, _,_ = adcTomV(roi_data[ref_ch], cstop=0, skip_cell=0, offsets=None)
        x = np.arange(len(ref_pulse))
        

        _, ax = plt.subplots(figsize=(8,5), dpi=150)

        ax.plot(x, ref_pulse, "o--", label="Reference Pulse")


        ax.scatter(edge,
                   ref_pulse[edge],
                   color="red",
                   s=80,
                   label="Detected Edge")

        ax.axvline(peak_pos,
                   linestyle="--",
                   color="grey",
                   label="Peak")

        ax.set_title(f"Event {event_id}  |  Ref Channel {ref_ch}")
        ax.set_xlabel("Sample")
        ax.set_ylabel("ADC")

        ax.legend()
        ax.grid()

        fname = ref_dir / f"evt{event_id}_refch{ref_ch}.png"
        plt.tight_layout()
        plt.savefig(fname)
        plt.close()


def mapToPixels(geometry, image, pixel_map, gch):
    '''
    For both charge and arrival time
    Need to develop logic to plot arrival times of a single gain 
    '''
    mask = (gch % geometry.N_CH_PER_DDB != geometry.N_CH_PER_DDB - 1)
    #size = geometry.N_PCM * geometry.N_DDB
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
    Saves a high resolution tiff image of the input event ID
    Displays pixel id, the global channel index in (LG, HG) format. 
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

    ax.set_title(f"Event {event_id}")
    ax.set_xticks([])
    ax.set_yticks([])

    output_path = output_dir / f"{event_id}.png"
    plt.savefig(output_path, bbox_inches='tight')
    plt.close(fig)

def chargeDist(event_id, image, label, xlabel,  output_dir):
    '''
    Saves the charge and time distributions
    Statistics are also displayed 
    '''
    fig, ax = plt.subplots(figsize = (8, 8), dpi = 300)
    image = image.flatten()
    # Statistics
    
    mean_val = np.mean(image)
    std_val = np.std(image)
    min_val = np.min(image)
    max_val = np.max(image)
    med_val = np.median(image)
    mad_val = np.median(np.abs(image - np.median(image)))

    
    stats_text = (
        f"Mean = {mean_val:.2f}  Med  = {med_val:.2f}\n"
        f"Std  = {std_val:.2f}   MAD  = {mad_val:.2f}\n"
        f"Min  = {min_val:.2f}\n"
        f"Max  = {max_val:.2f}\n"
        f""
    )

    

    ax.hist(image, bins = 'auto')
    ax.axvline(mean_val, color="red", linestyle="--", label="Mean")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Counts")
    ax.set_title(label)
    
    ax.text(
        0.97, 0.97,
        stats_text,
        transform=ax.transAxes,
        fontsize=10,
        verticalalignment='top',
        horizontalalignment='right',
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8)
    )
    charge_dir = output_dir / "Dist"
    charge_dir.mkdir(parents=True, exist_ok=True)

    output_path = charge_dir /f"{event_id}_{label.replace(' ', '_')}.png"
    plt.savefig(output_path, bbox_inches = 'tight')
    plt.close(fig)

# PLOT THE PULSES


def plotLGHGPulseWithWindow(roi_data, cstop, offsets, skip_cell, geometry, global_ch, event_index, output_dir):
    
    """
    Plots LG and HG pulses of a given pixel
    and saves as pcm_ddb_ch.png
    """

    lch_id, ddb_id, pcm_id = geometry.local_channel_id(global_ch)

    # LG is even channel, HG is odd channel
    hg_ch = global_ch
    lg_ch = hg_ch - 1
    
    block_size = 1024
    
       
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
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
    ax.plot(time_lg, pulse_lg, label=f"LG pcm = {pcm_id},  ddb  = {ddb_id} ch = {lch_id_lg}", color = 'blue')
    #ax.axvline(arrival_time_lg, linestyle="-", color='blue', alpha=0.7)
    ax.plot(time_hg, pulse_hg, label=f"HG pcm = {pcm_id},  ddb  = {ddb_id} ch = {lch_id_hg}", color = 'red')
    #ax.axvline(arrival_time_hg, linestyle="-", color='red', alpha=0.7)

    ax.axvline(time_lg[start_hg], linestyle="--", color='red', alpha=0.3)
    ax.axvline(time_lg[end_hg], linestyle="--", color='red', alpha=0.3)
    ax.axvline(time_lg[start_lg], linestyle="--", color='blue', alpha=0.3)
    ax.axvline(time_lg[end_lg], linestyle="--", color='blue', alpha=0.3)
    mask_lg = (time_lg < time_lg[start_lg]) | (time_lg > time_lg[end_lg])
    mask_hg = (time_hg < time_hg[start_hg]) | (time_hg > time_hg[end_hg])
    ax.axhline(np.median(pulse_lg[mask_lg]), linestyle=":", color='blue', alpha=0.7, label = f"Baseline Median {np.median(pulse_lg[mask_lg]):.2f} mV")
    ax.axhline(np.median(pulse_hg[mask_hg]), linestyle=":", color='red', alpha=0.7, label = f"Baseline Median {np.median(pulse_hg[mask_hg]):.2f} mV")
    ax.axhline(np.mean(pulse_lg[mask_lg]), linestyle="--", color='blue', alpha=0.7, label = f"Baseline Mean {np.mean(pulse_lg[mask_lg]):.2f} mV")
    ax.axhline(np.mean(pulse_hg[mask_hg]), linestyle="--", color='red', alpha=0.7, label = f"Baseline Mean {np.mean(pulse_hg[mask_hg]):.2f} mV")

    ax.set_xlabel("Time Cell")
    ax.set_ylabel("Amplitude (mV)")
    ax.set_title(f"PCM {pcm_id} | DDB {ddb_id} | Local Ch {lch_id}")
    ax.legend()
    ax.grid(True)

    filename = f"evt{event_index}_pcm{pcm_id}_ddb{ddb_id}_ch{lch_id_lg}_{lch_id_hg}.png"
    pulse_dir = output_dir / "pulse_profiles"
    pulse_dir.mkdir(parents=True, exist_ok=True)
    output_path = pulse_dir / filename
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close(fig)


def saveImages(event_index, roi_slice, cstop_slice, skip_cell_slice, offsets, geometry, pixel_map, gch, output_dir):
    charge_image, time_image, _ = imageGen(roi_slice, cstop_slice, skip_cell_slice, offsets, geometry)
    
    ch_image_LG, ch_image_HG = mapToPixels(geometry, charge_image, pixel_map, gch)
    t_image_LG, t_image_HG = mapToPixels(geometry, time_image, pixel_map, gch)
    return ch_image_LG, ch_image_HG, t_image_LG, t_image_HG


def processEvent(event_index, roi_slice, cstop_slice, skip_cell_slice, offsets, geometry, pixel_map, gch, output_dir):
    #print(event_index)
    charge_image, time_image, sat_mask = imageGen(roi_slice, cstop_slice, skip_cell_slice, offsets, geometry)
    
    ch_image_LG, ch_image_HG = mapToPixels(geometry, charge_image, pixel_map, gch)
    _, t_image_HG = mapToPixels(geometry, time_image, pixel_map, gch)
    _, satmask_HG = mapToPixels(geometry, sat_mask, pixel_map, gch)
    
    # Save preview only (raw save if needed)
    #saveImage(f"{output_dir}/{event_index}_LG", image_LG)
    #saveImage(f"{output_dir}/{event_index}_HG", image_HG)

    # Save HiRes
    #saveImageHiRes(f"{event_index}_HG", "Integrated Charge", ch_image_HG, output_dir, pixel_map, geometry)
    
    #saveImageHiRes(f"{event_index}_LG", "Integrated Charge",  ch_image_LG, output_dir, pixel_map, geometry,cmap = 'cmyt.xray')
    #saveImageHiRes(f"{event_index}_time", "Arrival Time", t_image_HG, output_dir, pixel_map, geometry, cmap='plasma')
    #saveImageHiRes(f"{event_index}_LG_time", "Arrival Time", t_image_LG, output_dir, pixel_map, geometry, cmap='plasma')
    #chargeDist(event_index, ch_image_HG, f"Charge Distribution (HG)- Event {event_index}", "HG Charge", output_dir)
    #chargeDist(event_index, ch_image_LG, f"Charge Distribution (LG) - Event {event_index}","LG Charge", output_dir)
    #chargeDist(event_index, t_image_HG, f"Arrival Time Distribution - Event {event_index}", "Arrival Time",  output_dir)
    #plotLGHGPulseWithWindow( roi_slice, cstop_slice, offsets, skip_cell_slice, geometry, 2, event_index, output_dir)
#
    return {
            "event_id": event_index,
            "image_LG": ch_image_LG,
            "image_HG": ch_image_HG,
            #"time_LG": t_image_LG,
            "time_HG": t_image_HG,
            "saturation_mask": satmask_HG
            }       
    #return event_index


      
      
      
      
################################
######ONLY FOR TESTING#######    

def main():
    with h5py.File("../output/evts.h5", "r") as f:

        roi_all = f["adc/roi_data"]
        cstop_all = f["adc/cstop"]
        skip_cell =f["adc/skip_cell"]
        event_number = 1
        roi_slice = roi_all[event_number]
        cstop_slice = cstop_all[event_number]
        skip_cell_slice = skip_cell[event_number]
        #offsets = np.loadtxt("../DRS_OFFSET/all_cdm_ddb_drsoffsets_fro_09112024_1.cofsm")
        config = load_config("config/config.yaml")
        offsets = np.loadtxt(offset_filepath)
        

        geometry = CameraLayout(config)
        output_dir = Path("../test_output")
        output_dir.mkdir(exist_ok=True)

        glob_ch_indices = np.arange(0, geometry.N_GLOBAL_CH, 1)
        mask = (glob_ch_indices % geometry.N_CH_PER_DDB != geometry.N_CH_PER_DDB - 1)
        glob_ch_indices = glob_ch_indices[mask]
        plotReferencePulses(event_number, roi_slice, geometry, output_dir)
        for ch in glob_ch_indices[1::2]:
            #print(ch)
            plotLGHGPulseWithWindow(roi_slice, cstop_slice, offsets, skip_cell_slice, geometry, ch, event_number, output_dir)
        
        print("Done")
if __name__ == "__main__":
    main()