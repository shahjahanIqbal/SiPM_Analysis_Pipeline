import h5py
import numpy as np
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm

import json
import os
import numpy as np
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm

from astropy import units as u
from concurrent.futures import ProcessPoolExecutor, as_completed


from ctapipe.io import EventSource, DataWriter, EventSource
from ctapipe.core.provenance import Provenance

from ctapipe.instrument import (
    CameraGeometry,
    CameraReadout,
    CameraDescription,
    TelescopeDescription,
    SubarrayDescription,
    OpticsDescription,
    SubarrayDescription,
    TelescopeDescription,
    OpticsDescription
)
from ctapipe.containers import (ArrayEventContainer, 
                                SchedulingBlockContainer, 
                                ObservationBlockContainer,
                                ImageParametersContainer, 
                                ArrayEventContainer
                                )


from ctapipe.instrument.camera.description import CameraDescription


from config_loader import load_config
from geometry import CameraLayout
from config_loader import load_config
from image_gen import processEvent



config = load_config("config/config.yaml")
geometry = CameraLayout(config)

N_GLOBAL_CH = geometry.N_GLOBAL_CH
n_samples = geometry.roi
from astropy import units as u
import numpy as np
from astropy.coordinates import EarthLocation

reference_location = EarthLocation(
    lat = 0 * u.deg,
    lon = 0 * u.deg,
    height = 0 * u.m
)


def build_subarray(geometry):

    size = 22.1
    pixel_count = geometry.N_PCM * geometry.N_DDB * 4

    pix_id = np.arange(pixel_count)

    x = (np.arange(-8,8) * size) + size/2
    y = (np.arange(-8,8) * size) + size/2
    pix_x, pix_y = np.meshgrid(x, y)

    pix_x = pix_x.ravel() * u.mm
    pix_y = pix_y.ravel() * u.mm

    pix_area = (size/1.05)**2 * np.ones(pixel_count) * u.mm**2

    geom = CameraGeometry(
        name="SiPM",
        pix_id=pix_id,
        pix_x=pix_x,
        pix_y=pix_y,
        pix_area=pix_area,
        pix_type="square"
    )

    reference_pulse = np.zeros((N_GLOBAL_CH, n_samples))

    readout = CameraReadout(
        name="SiPM",
        sampling_rate=1*u.GHz,
        reference_pulse_shape=reference_pulse,
        reference_pulse_sample_width=1*u.ns,
        n_channels=geometry.N_GLOBAL_CH,
        n_pixels=256,
        n_samples=geometry.roi
    )

    camera = CameraDescription(
        name="SiPM",
        geometry=geom,
        readout=readout
    )

    optics = OpticsDescription(
        name="Optics",
        size_type="UNKNOWN",
        n_mirrors=1,
        equivalent_focal_length=1*u.m,
        effective_focal_length=1*u.m,
        mirror_area=1*u.m**2,
        n_mirror_tiles=1,
        reflector_shape="UNKNOWN"
    )

    telescope = TelescopeDescription(
        name="Tel",
        optics=optics,
        camera=camera
    )



    subarray = SubarrayDescription(
        name="Array",
        tel_positions={1: [0,0,0]*u.m},
        tel_descriptions={1: telescope},
        reference_location=reference_location
    )

    return subarray


N_GLOBAL_CH = geometry.N_GLOBAL_CH
n_samples = geometry.roi
PROV = Provenance()
PROV.start_activity("dl1_write")
class SyntheticSource(EventSource):

    def __init__(self, subarray):
        super().__init__(input_url="synthetic")
        self._subarray = subarray
        sb = SchedulingBlockContainer()
        sb.sb_id = np.uint64(1)

        ob = ObservationBlockContainer()
        ob.obs_id = np.uint64(1)
        ob.sb_id = np.uint64(1)

        self._scheduling_blocks = {1: sb}
        self._observation_blocks = {1: ob}

    @staticmethod
    def is_compatible(file_path):
        return False

    @property
    def subarray(self):
        return self._subarray

    @property
    def is_simulation(self):
        return False

    @property
    def datalevels(self):
        return ("R1", "DL1")

    @property
    def scheduling_blocks(self):
        return self._scheduling_blocks

    @property
    def observation_blocks(self):
        return self._observation_blocks
    @property
    def obs_ids(self):
        return [1]

    def _generator(self):
        while False:
            yield



pixel_map = geometry.loadPixelMap(f"geometry/{geometry.camera_name}.h5")
#offsets = np.loadtxt("../DRS_OFFSET/offsetcal_January13012026.txt")
offsets = np.loadtxt(config["calib"]["drsoffset"])

gch = np.arange(geometry.N_GLOBAL_CH)

input_file = "output/s0534+2201_339_flashCAL_14122025_2_EVBdata.h5"
output_file = "events_cta/dl1_ctapipe_ready.h5"

Path(output_file).parent.mkdir(parents = True, exist_ok = True)

subarray = build_subarray(geometry)

source = SyntheticSource(subarray=subarray)

with h5py.File(input_file, "r") as f:

    roi_all = f["adc/roi_data"]
    cstop_all = f["adc/cstop"]
    skip_cell = f["adc/skip_cell"]

    n_events = roi_all.shape[0]

    with ProcessPoolExecutor() as executor:

        futures = []

        for i in range(n_events):

            futures.append(
                executor.submit(
                    processEvent,
                    i,
                    roi_all[i],
                    cstop_all[i],
                    skip_cell[i],
                    offsets,
                    geometry,
                    pixel_map,
                    gch,
                    None
                )
            )

        with DataWriter(event_source=source, output_path=output_file, overwrite = True, write_dl1_images=True) as writer:

            for future in tqdm(as_completed(futures), total=n_events):

                result = future.result()

                event = ArrayEventContainer()

                # ----- Event index -----
                event.index.obs_id = np.uint64(1)
                event.index.event_id = np.uint64(result["event_id"])

                event.trigger.tels_with_trigger = [1]
                tel_trigger = event.trigger.tel[1]
                tel_trigger.time = 0.0

                tel = event.dl1.tel[1]
                # Required by DataWriter
                tel.is_valid = True
                tel.parameters = {}
                # ----- Telescope pointing (needed later by reconstructor) -----
                #event.pointing.tel[1].azimuth = 0.0
                #event.pointing.tel[1].altitude = 1.0

                tel.image = result["image_HG"].flatten().astype(np.float32)
                tel.peak_time = np.zeros_like(tel.image)
                tel.parameters = ImageParametersContainer()

                writer(event)
PROV.finish_activity("dl1_write")                