#!/usr/bin/env python3
from ctapipe.io import EventSource
from ctapipe.visualization import CameraDisplay
import numpy as np
import os
import astropy.units as u
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
from matplotlib.widgets import Button
import argparse
from pathlib import Path
import sys



fig = plt.figure(figsize=(13, 6))


ax_btn_skip = fig.add_axes([0.57, 0.15, 0.10, 0.07])
ax_btn_next = fig.add_axes([0.69, 0.15, 0.10, 0.07])
ax_btn_exit = fig.add_axes([0.81, 0.15, 0.10, 0.07])
btn_next = Button(ax_btn_next, 'Next ▶',  color='#afccc6', hovercolor='#7fb3a8')
btn_skip = Button(ax_btn_skip, 'Skip 10', color='#d0e8e4', hovercolor='#7fb3a8')
btn_exit = Button(ax_btn_exit, 'Exit', color='#d0e8e4', hovercolor='#7fb3a8')

# Protected axes
PROTECTED = {ax_btn_next, ax_btn_skip, ax_btn_exit}


def clear_axes():
    '''
        Iterates over fig.axes and removes any axis not in the PROTECTED set (the
        three button axes). Called at the start of each draw_event to avoid stale
        camera displays and parameter tables accumulating in the figure.
    '''
    for ax in fig.axes[:]:          
        if ax not in PROTECTED:
            ax.remove()


def draw_event(event):
    '''
        Adds a camera display axis and a parameter table axis. Uses CameraDisplay to
        render the DL1 image. If Hillas parameters are stored, overlays the fitted
        ellipse, the major-axis line, and the centre of gravity marker, and populates
        a table with Hillas and concentration values. Calls fig.canvas.draw_idle().
    '''
    clear_axes()

    ax_cam = fig.add_axes([0.02, 0.12, 0.50, 0.83])
    ax_info = fig.add_axes([0.57, 0.12, 0.40, 0.83])
    ax_info.axis('off')

    tel_id = list(event.dl1.tel.keys())[0]
    tel_geo = source.subarray.tel[tel_id].camera.geometry
    image = event.dl1.tel[tel_id].image
    obs_id = event.index.obs_id
    event_id = event.index.event_id

    disp = CameraDisplay(tel_geo, image=image, ax=ax_cam)
    disp.cmap = 'viridis'
    disp.add_colorbar(ax=ax_cam, label="Charge [pC]")
    ax_cam.set_title(f"Run {obs_id} | Event {event_id} | Tel {tel_id}", fontsize=11, fontweight='bold')

    params = event.dl1.tel[tel_id].parameters
    hillas = params.hillas if params is not None else None
    conc = params.concentration if params is not None else None


    if hillas is not None and np.isfinite(hillas.length.value):
        x = hillas.x.to_value(u.mm)
        y = hillas.y.to_value(u.mm)
        length = hillas.length.to_value(u.mm)
        width = hillas.width.to_value(u.mm)
        psi = hillas.psi.to_value(u.rad)
        dx = length * np.cos(psi)
        dy = length * np.sin(psi)

        ax_cam.add_patch(Ellipse(
            xy=(x, y), width=2 * length, height=2 * width, angle=np.degrees(psi), edgecolor='#e77e51', facecolor='none', linewidth=1.8, linestyle='--', zorder=5,
        ))
        ax_cam.plot(x, y, '+', color='#e77e51', markersize=10, markeredgewidth=2, zorder=6)
        ax_cam.plot([x - dx, x + dx], [y - dy, y + dy], color='#e77e51', linewidth=1.4, zorder=5)

        rows = [
            ["Length", f"{length:.2f} mm"],
            ["Width", f"{width:.2f} mm"],
            ["Psi", f"{hillas.psi.to_value(u.deg):.2f}°"],
            ["Skewness", f"{hillas.skewness:.3f}"],
            ["Kurtosis", f"{hillas.kurtosis:.3f}"],
            ["Intensity", f"{hillas.intensity:.2f} pC"],
            ["CoG x", f"{x:.2f} mm"],
            ["CoG y", f"{y:.2f} mm"],
        ]
        if conc is not None:
            rows += [
                ["Conc CoG", f"{conc.cog:.4f}"],
                ["Conc Core", f"{conc.core:.4f}"],
                ["Conc Pixel", f"{conc.pixel:.4f}"],
            ]
        table = ax_info.table(
            cellText = rows,
            colLabels = ["Parameter", "Value"],
            loc = 'upper center',
            cellLoc = 'center',
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1, 1.8)

        for col in range(2):
            table[0, col].set_facecolor('#43658d')
            table[0, col].set_text_props(color='white', fontweight='bold')
        for row in range(1, len(rows) + 1):
            fc = '#afccc6' if row % 2 == 0 else '#dceee9'
            for col in range(2):
                table[row, col].set_facecolor(fc)
    else:
        ax_info.text(0.5, 0.5, "No Hillas parameters\nstored for this event", ha='center', va='center', fontsize=12, color='gray', transform=ax_info.transAxes)

    fig.canvas.draw_idle()


def on_next(click):
    '''
        Calls next() on the module-level event_iter. Catches StopIteration and
        replaces the display with an end-of-file text message.
    '''
    try:
        state["event"] = next(event_iter)
        draw_event(state["event"])
    except StopIteration:
        clear_axes()
        ax = fig.add_axes([0.02, 0.12, 0.95, 0.83])
        ax.text(0.5, 0.5, "End of file", ha='center', va='center', fontsize=16, transform=ax.transAxes)
        ax.axis('off')
        fig.canvas.draw_idle()


def on_skip(click):
    '''
        Skips the next 10 events in the event iterator. Catches StopIteration and
        replaces the display with an end-of-file text message.
    '''
    try:
        for _ in range(9):
            next(event_iter)
        state["event"] = next(event_iter)
        draw_event(state["event"])
    except StopIteration:
        on_next(click)

def on_exit(click):
    '''
    Exits the program gracefully when the Exit button is clicked.
    '''
    plt.close('all')
    sys.exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Display dl1 images")
    parser.add_argument("dl1", type=str, help = "Path to the dl1 file" )
    args = parser.parse_args()
    file_path = args.dl1
    if not Path(file_path).exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    source = EventSource(input_url=file_path, max_events=None)
    event_iter = iter(source)
    state = {"event": next(event_iter)}

    btn_next.on_clicked(on_next)
    btn_skip.on_clicked(on_skip)
    btn_exit.on_clicked(on_exit)

    draw_event(state["event"])
    plt.show()