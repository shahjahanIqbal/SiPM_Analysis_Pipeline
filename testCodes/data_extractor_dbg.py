#!/usr/bin/env python3
import numpy as np
import logging


def dataExtractor(event_id, event_info, data, geometry, ROI):
    '''
        Input: event_id (int), event_info (dict with keys "packets" and "quality"),
               data (1D uint32 array, pre-sliced to the event span),
               geometry (CameraLayout), ROI (int, number of ADC samples per channel)
        Output: dict with keys event_id, event_number, adc (N_GLOBAL_CH x ROI int16),
                valid_mask, roi_cell, cstop, skip_cell, time_stamp, time_elapsed, quality
        Iterates over all packets belonging to an event. For each channel it reads
        the ROI cell count, skip cell, and cstop from the per-channel header word,
        then unpacks the interleaved 14-bit ADC samples stored two per 32-bit word.
        Channels absent from the valid-channel bitmask are skipped. The global channel
        index is computed via geometry.global_channel_id with a workaround for
        labelling of channel 8 as channel 0.
    '''

    packets = event_info["packets"]
    quality = event_info["quality"]
    N_GLOBAL_CH = geometry.N_GLOBAL_CH

    
    event_adc = np.zeros((N_GLOBAL_CH, ROI), dtype=np.int16)
    valid_mask = np.zeros(N_GLOBAL_CH, dtype=bool)
    cstop_arr = np.zeros(N_GLOBAL_CH, dtype=np.int16)
    skip_arr = np.zeros(N_GLOBAL_CH, dtype=np.int16)
    roi_cell = np.zeros(N_GLOBAL_CH, dtype=np.int16)
    event_number = None
    
    for si, ei in packets:
    
    # Access Valid Channels Flags
        validChannels = (data[si + 6] >> 18) & 0x1FF 
        event_number = data[si + 2] & 0x7FFFFFFF
        #logging.debug(f"Event Number = {data[si+2]} \tCDM ID: {(data[si+5] >> 18) & 0x1f} \tDDB ID: {(data[si+5]>>16) & 0x3}\tValid Channel Flag: {np.binary_repr(validChannels)}")
        hdr_ind = si + 7
        
        CDM_ID = (data[si+5] >> 18) & 0x1f
        DDB_ID = (data[si+5]>>16) & 0x3
        
        for ch in range(geometry.N_CH_PER_DDB):
        
            
            print(f'DBG ch={ch} hdr_ind={hdr_ind} validChannels={validChannels:#x} ROI={data[hdr_ind]&0x7ff}', flush=True)
            if hdr_ind >= ei: # Checks if the loop exceeds DDB length while extracting channel data
                logging.error(f"Reached end of DDB data. Event header index (<hdr_ind>) exceeded end frame index (<ei>) \nEvent ID: {event_number}\tCDM ID: {CDM_ID}\tDDB ID: {DDB_ID}\t Channel: {ch}")
                break
            
            ROI_Cell = data[hdr_ind] & 0x7ff
            Skip_Cell = data[hdr_ind] >> 11 & 0x3ff
            CStop = data[hdr_ind]>>21 & 0x3ff   
            time_stamp = data[si + 3] & 0x00ffffff
            time_elapsed = data[si + 4] & 0x7fffffff 
            dat_ind = hdr_ind + 1
            
            if (validChannels >> ch) & 1:
                data_write = np.zeros(ROI_Cell, dtype=np.int16)

                # Each 28 bit ADC sample is stored in 14 bit LSB and 14 bit MSB format within a 32 bit word. 

                # Channel 8 is represented by channel ID 0. Set it to 8 for clarity in the output file.
                channel_id = (data[dat_ind] >> 28) & 0x7
                
                
                if ch == 8 and channel_id == 0:     
                    channel_id = 8                  # Fix for channel 8 being labelled as channel 0  (--_--)
              

                glob_ch_index = geometry.global_channel_id(CDM_ID, DDB_ID, channel_id) 
                valid_mask[glob_ch_index] = True
                cstop_arr[glob_ch_index] = CStop
                skip_arr[glob_ch_index] = Skip_Cell
                roi_cell[glob_ch_index] = ROI_Cell
                

                for index in range(ROI_Cell // 2):
                    data_write[2 * index] = data[index + dat_ind] & 0x3fff
                    data_write[2 * index + 1] = (data[index + dat_ind] >> 14) & 0x3fff
                #logging.debug(f"Extracting ADC ROI DATA of channel {channel_id}...")


                event_adc[glob_ch_index, :ROI_Cell] = data_write

            else:
                logging.debug(f"Channel {ch} not valid, skipping ADC ROI data extraction.")
                hdr_ind = dat_ind + ROI_Cell // 2
                continue
            
            hdr_ind = dat_ind + ROI_Cell // 2
    return {
        "event_id": event_id,
        "event_number": event_number,
        "adc": event_adc,
        "valid_mask": valid_mask,
        "roi_cell": roi_cell,
        "cstop": cstop_arr,
        "skip_cell": skip_arr,
        "time_stamp": time_stamp,
        "time_elapsed": time_elapsed,
        "quality": quality
        }
