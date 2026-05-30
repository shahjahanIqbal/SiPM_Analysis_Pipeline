#!/usr/bin/env python3
import numpy as np
import h5py
import logging
from pathlib import Path

class CameraLayout():
    '''
    Generates the pixel readout map. 
    This algorithm assumes that the readout is done in a column-first manner 
    from bottom to top and left to right (apparenty its not -_-)
    '''

    def __init__(self,config_file):
    
        self.cam = config_file["camera_geometry"]
        self.N_CH_PER_DDB = self.cam["channel_count"]
        self.N_DDB = self.cam["ddb_count"]
        self.N_PCM = self.cam["pcm_count"]
        self.N_GLOBAL_CH = self.N_PCM * self.N_DDB * self.N_CH_PER_DDB
        self.camera_name = self.cam["name"]
        self.roi = self.cam["readout"]["roi_samples"]

        
    
    def createPixelMap(self):
        '''
        Generates the 16x16 pixel index map by assigning flat pixel indices to
        (row, col) positions following the column-major DDB ordering within each PCM
        block. Creates the geometry directory if absent and saves the map as a
        gzip-compressed HDF5 dataset PIXEL_MAP alongside a CSV for inspection.

        '''
        CHANNEL_COUNT = 4 # 4 LG 4 HG and 1 Reference Channel
        total_pixels = CHANNEL_COUNT * self.N_DDB * self.N_PCM
        pixel_indices = np.arange(0, total_pixels, 1)
        DDB_INDEX = 0
        self.rows = self.cam["layout"]["rows"]
        self.cols = self.cam["layout"]["cols"]
        IMG = np.zeros((self.rows, self.cols))
        IMG = np.zeros((16,16))
        pcm_size = 4
        
        ddb_size = 4
        pcm_array = np.zeros((pcm_size, pcm_size))
        for u in range(pcm_size):
            for v in range(pcm_size):
                pcm_row = 4 *v
                pcm_col = 4 * u
                for x in range(ddb_size):
                    for y in range(ddb_size):
                    
                        ddb_row_ind =  y
                        ddb_col_ind =  x
                        
                        pcm_array[ddb_row_ind, ddb_col_ind] = pixel_indices[ 16 * DDB_INDEX + (4 * x + y)]
                        IMG[pcm_row: pcm_row + 4, pcm_col: pcm_col + 4] = pcm_array
                DDB_INDEX += 1
        path = Path(f"../geometry/")
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)

        np.savetxt(f"../geometry/{self.camera_name}.csv", IMG, delimiter=',', fmt = '%d')
        path = path/f"{self.camera_name}.h5"
        with h5py.File(path, "w") as f:
            f.create_dataset(
                "PIXEL_MAP",
                data=IMG,
        dtype="i4",          
        compression="gzip",
        compression_opts=4
    )

    def loadPixelMap(self, filepath):
        '''
        Input: filepath (str or Path) pointing to the .h5 pixel map file
        Output: 2D int numpy array of shape (rows, cols)
        Opens the HDF5 file and reads the PIXEL_MAP dataset. If the file is not found,
        logs a warning, calls createPixelMap to regenerate it from the current config,
        and retries. Returns the map as a plain int array.

        '''
        filepath = Path(filepath)

        if not filepath.exists():
            logging.error(f"Pixel Map not found in {filepath}. Generating with default specifications") 

            self.createPixelMap()
            filepath = Path(f"../geometry/{self.camera_name}.h5")
   
        with h5py.File(filepath, "r") as f:
            pixel_map = f["PIXEL_MAP"][:].astype(int)

        return pixel_map
    
    def global_channel_id(self, cdm, ddb, ch):
        '''
        Input: cdm (int), ddb (int), ch (int) - CDM index, DDB index, local channel
        Output: int, the flat global channel index
        Computes gch = cdm * (N_DDB * N_CH_PER_DDB) + ddb * N_CH_PER_DDB + ch.
        Used throughout the extraction pipeline to map hardware addresses to array
        positions.

        '''
        
        return cdm * (self.N_DDB * self.N_CH_PER_DDB) + ddb * self.N_CH_PER_DDB + ch
    
    def local_channel_id(self, gch):
        '''
        Input: gch (int), the global channel index
        Output: tuple (lch, lddb, lpcm) — local channel, DDB, and PCM indices
        Inverts global_channel_id by successive integer division and modulo. Used
        when selecting DRS offset slices and labelling waveform plots.
        '''

        Qch = gch // self.N_CH_PER_DDB
        lch = gch % self.N_CH_PER_DDB

        Qddb = Qch // self.N_DDB
        lddb = Qch % self.N_DDB

        Qpcm = Qddb // self.N_PCM
        lpcm = Qddb % self.N_PCM
        
        return lch, lddb, lpcm 

        