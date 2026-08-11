import os
import logging
import click
import sys
from pathlib import Path

'''
Pipeline logos. Pick you poison :D 
Credits: https://fsymbols.com/generators/carty/ 
         https://patorjk.com/software/taag/#p=display&f=Graffiti&t=Type+Something+&x=none&v=4&h=4&w=80&we=false
'''

'''banner = r"""                                                                                                                                   
 @@@@@@    @@@@@@@  @@@   @@@@@@@   @@@@@@   @@@@@@@@@@      @@@@@@@   @@@  @@@@@@@   @@@@@@@@  @@@       @@@  @@@  @@@  @@@@@@@@  
@@@@@@@   @@@@@@@@  @@@  @@@@@@@@  @@@@@@@@  @@@@@@@@@@@     @@@@@@@@  @@@  @@@@@@@@  @@@@@@@@  @@@       @@@  @@@@ @@@  @@@@@@@@  
!@@       !@@       @@!  !@@       @@!  @@@  @@! @@! @@!     @@!  @@@  @@!  @@!  @@@  @@!       @@!       @@!  @@!@!@@@  @@!       
!@!       !@!       !@!  !@!       !@!  @!@  !@! !@! !@!     !@!  @!@  !@!  !@!  @!@  !@!       !@!       !@!  !@!!@!@!  !@!       
!!@@!!    !@!       !!@  !@!       @!@!@!@!  @!! !!@ @!@     @!@@!@!   !!@  @!@@!@!   @!!!:!    @!!       !!@  @!@ !!@!  @!!!:!    
 !!@!!!   !!!       !!!  !!!       !!!@!!!!  !@!   ! !@!     !!@!!!    !!!  !!@!!!    !!!!!:    !!!       !!!  !@!  !!!  !!!!!:    
     !:!  :!!       !!:  :!!       !!:  !!!  !!:     !!:     !!:       !!:  !!:       !!:       !!:       !!:  !!:  !!!  !!:       
    !:!   :!:       :!:  :!:       :!:  !:!  :!:     :!:     :!:       :!:  :!:       :!:        :!:      :!:  :!:  !:!  :!:       
:::: ::    ::: :::   ::   ::: :::  ::   :::  :::     ::       ::        ::   ::        :: ::::   :: ::::   ::   ::   ::   :: ::::  
:: : :     :: :: :  :     :: :: :   :   : :   :      :        :        :     :        : :: ::   : :: : :  :    ::    :   : :: ::   
                                                                                                                                   """
'''
'''banner = r"""
  █████████    █████████  █████   █████████    █████████   ██████   ██████    ███████████  █████ ███████████  ██████████ █████       █████ ██████   █████ ██████████
 ███▒▒▒▒▒███  ███▒▒▒▒▒███▒▒███   ███▒▒▒▒▒███  ███▒▒▒▒▒███ ▒▒██████ ██████    ▒▒███▒▒▒▒▒███▒▒███ ▒▒███▒▒▒▒▒███▒▒███▒▒▒▒▒█▒▒███       ▒▒███ ▒▒██████ ▒▒███ ▒▒███▒▒▒▒▒█
▒███    ▒▒▒  ███     ▒▒▒  ▒███  ███     ▒▒▒  ▒███    ▒███  ▒███▒█████▒███     ▒███    ▒███ ▒███  ▒███    ▒███ ▒███  █ ▒  ▒███        ▒███  ▒███▒███ ▒███  ▒███  █ ▒ 
▒▒█████████ ▒███          ▒███ ▒███          ▒███████████  ▒███▒▒███ ▒███     ▒██████████  ▒███  ▒██████████  ▒██████    ▒███        ▒███  ▒███▒▒███▒███  ▒██████   
 ▒▒▒▒▒▒▒▒███▒███          ▒███ ▒███          ▒███▒▒▒▒▒███  ▒███ ▒▒▒  ▒███     ▒███▒▒▒▒▒▒   ▒███  ▒███▒▒▒▒▒▒   ▒███▒▒█    ▒███        ▒███  ▒███ ▒▒██████  ▒███▒▒█   
 ███    ▒███▒▒███     ███ ▒███ ▒▒███     ███ ▒███    ▒███  ▒███      ▒███     ▒███         ▒███  ▒███         ▒███ ▒   █ ▒███      █ ▒███  ▒███  ▒▒█████  ▒███ ▒   █
▒▒█████████  ▒▒█████████  █████ ▒▒█████████  █████   █████ █████     █████    █████        █████ █████        ██████████ ███████████ █████ █████  ▒▒█████ ██████████
 ▒▒▒▒▒▒▒▒▒    ▒▒▒▒▒▒▒▒▒  ▒▒▒▒▒   ▒▒▒▒▒▒▒▒▒  ▒▒▒▒▒   ▒▒▒▒▒ ▒▒▒▒▒     ▒▒▒▒▒    ▒▒▒▒▒        ▒▒▒▒▒ ▒▒▒▒▒        ▒▒▒▒▒▒▒▒▒▒ ▒▒▒▒▒▒▒▒▒▒▒ ▒▒▒▒▒ ▒▒▒▒▒    ▒▒▒▒▒ ▒▒▒▒▒▒▒▒▒▒ 
                                                                                                                                                                    
                                                                                                                                                                    
                                                                                                                                                                    """'''



banner = r"""
░██████╗░█████╗░██╗░█████╗░░█████╗░███╗░░░███╗  ██████╗░██╗██████╗░███████╗██╗░░░░░██╗███╗░░██╗███████╗
██╔════╝██╔══██╗██║██╔══██╗██╔══██╗████╗░████║  ██╔══██╗██║██╔══██╗██╔════╝██║░░░░░██║████╗░██║██╔════╝
╚█████╗░██║░░╚═╝██║██║░░╚═╝███████║██╔████╔██║  ██████╔╝██║██████╔╝█████╗░░██║░░░░░██║██╔██╗██║█████╗░░
░╚═══██╗██║░░██╗██║██║░░██╗██╔══██║██║╚██╔╝██║  ██╔═══╝░██║██╔═══╝░██╔══╝░░██║░░░░░██║██║╚████║██╔══╝░░
██████╔╝╚█████╔╝██║╚█████╔╝██║░░██║██║░╚═╝░██║  ██║░░░░░██║██║░░░░░███████╗███████╗██║██║░╚███║███████╗
╚═════╝░░╚════╝░╚═╝░╚════╝░╚═╝░░╚═╝╚═╝░░░░░╚═╝  ╚═╝░░░░░╚═╝╚═╝░░░░░╚══════╝╚══════╝╚═╝╚═╝░░╚══╝╚══════╝"""


@click.group()
@click.version_option(version = "1.0.0", prog_name = "SciCam Pipeline")
def cli():
    """SiPM Camera data reduction pipeline
    
    Run any command with --help for detailed instructions"""
    pass

# Data Extraction
@cli.command()

@click.option('--config', required = False, default = 'config/config.yaml', help = "Path to config.yaml. Default: config/config.yaml")
@click.option('--evb', required = False, help = "Path to the EVB file. Ignore if mentioned in config.yaml. Otherwise the filepath will be overwritten")
@click.option('--workers', '-w', required = False, default = None, type = int, help = " Number of parallel workers. Default value : cpu_count - 1")

def extract(evb, config, workers):
    
    from event_proc_parallel import EventProcessor, setup_logging, stop_logging
    from config_loader import load_config
    
    setup_logging()

    cfg = load_config(config)
    if evb is not None:
        cfg['data']['evbfilepath'] = evb

    pipeline = EventProcessor(config_path=config, config=cfg)
    
    try:
        pipeline.run(n_workers=workers)
    finally:
        stop_logging()

    


# H5 creation
@cli.command()
@click.argument("output_dir")
@click.option("--json-dir", default = "OBS_INFO", show_default = True, help = "Directory containing the json metadata files")
@click.option("--no-dl2", is_flag = True, default = False, help = "Skip Hillas parametrization. Use for processing calibration runs")
@click.option("--config", default = "config/config.yaml", help = "Path to the config file")

def createh5(output_dir, json_dir, no_dl2, config):
    import numpy as np
    from create_h5 import main, jsonFinder
    from config_loader import load_config
    from event_proc_parallel import setup_logging, stop_logging

    setup_logging()

    try:
        config = load_config(config)
        input_dir = Path(config['io']['output'])
        txt = input_dir/ "output_files.txt"

        if not txt.exists():
            raise click.ClickException(f"output_files.txt not found in {input_dir}.\nTry running the event processor.\nCommand: extract")
        input_files = np.atleast_1d(np.loadtxt(txt, dtype = str))

        click.echo(f"Files Found: {len(input_files)}")
        click.echo(f"File Directory: {Path(input_files[0]).parent}")
        processed_files, skipped, failed = [], [], {}

        for file in input_files:
            h5_file = Path(file)
            json_path = None
            if not no_dl2:
                try:
                    json_path = jsonFinder(h5_file, json_dir = Path(json_dir))
                except FileNotFoundError as e:
                    click.echo(click.style(f"Skipping {h5_file.name}: {e}", fg = 'yellow'))
                    logging.warning(f"Skipping {h5_file.name}: {e}")
                    skipped.append(h5_file.name)
                    continue
            else:
                click.echo(f"Calibration mode: skipping JSON and Hillas for {h5_file.name}")

            click.echo(f"Processing {h5_file.name}")
            try:
                main(
                    input_file = h5_file,
                    output_dir = Path(output_dir),
                    json_path = json_path,
                    config = config,
                    dl2_flag = not no_dl2 
                )
            except Exception as e:
                click.echo(click.style(f"Failed {h5_file.name}: {e}", fg = 'red'))
                logging.error(f"Failed {h5_file.name}: {e}")
                failed[h5_file.name] = str(e)
                continue
            processed_files.append(h5_file.name)
        if skipped:
            click.echo(click.style(f"Skipped {len(skipped)} (missing JSON): {', '.join(skipped)}", fg = 'yellow'))
        if failed:
            click.echo(click.style(f"Failed {len(failed)}: {', '.join(failed)}", fg = 'red'))
        if not processed_files:
            raise click.ClickException(f"No files processed ({len(skipped)} skipped: missing JSON, {len(failed)} failed). No DL1 output written.")
        return processed_files, skipped, failed
    finally:
        stop_logging()
# Save Images

@cli.command()
@click.argument("infile")
@click.argument("output_dir")
@click.option("--start", default=1, show_default=True, help="Start event index.")
@click.option("--end", default=None, type=int, help="End event index.")
@click.option("--no-lg", is_flag=True, help="Disable LG charge images.")
@click.option("--no-hg", is_flag=True, help="Disable HG charge images.")
@click.option("--no-time", is_flag=True, help="Disable arrival time images.")
@click.option("--waveform", is_flag=True, help="Save per-channel waveform plots.")
@click.option("--refpulse", is_flag=True, help="Save reference channel pulses.")
@click.option("--cdist-lg", is_flag=True, help="Save LG charge distribution.")
@click.option("--cdist-hg", is_flag=True, help="Save HG charge distribution.")
@click.option("--tdist", is_flag=True, help="Save arrival time distribution.")

def saveimg(infile, output_dir, start, end, no_lg, no_hg, no_time,waveform, refpulse, cdist_lg, cdist_hg, tdist):
    from save_raw_img import main
    
    main(
        infile_name = infile,
        output_dir = Path(output_dir),
        event_id_start = start,
        event_id_end = end,
        save_lg = not no_lg,
        save_hg = not no_hg,
        save_arrTime = not no_time,
        save_waveform = waveform,
        save_refPulse = refpulse,
        save_charge_dist_LG = cdist_lg,
        save_charge_dist_HG = cdist_hg,
        save_time_dist = tdist
    )
@cli.command()
@click.argument("dl1")

def viewdl1(dl1):
    if not Path(dl1).exists():
        raise click.ClickException(f"File not found: {dl1}")

    import runpy

    # Save and restore sys.argv so it doesn't bleed into subsequent commands
    _saved_argv = sys.argv[:]
    sys.argv = ['display_reco_events.py', dl1]
    try:
        runpy.run_path('display_reco_events.py', run_name="__main__")
    finally:
        sys.argv = _saved_argv

# Event classifier

#def classifyevents(dl1, model, name, threshold):
#
#    import numpy as np
#    import h5py
#    import joblib
#    from ctapipe.io import TableLoader
#
#    if not Path(dl1).exists():
#        raise click.ClickException(f"File not found: {dl1}")
#    
#    if not Path(model).exists():
#        raise click.ClickException(f"Model not found: {model}")
#    
#    rfa_model = joblib.load(model)


@cli.command()
@click.argument("output_dir", default = 'wrapper_test')
@click.option('--config', required = False, default = 'config/config.yaml', help = "Path to config.yaml. Default: config/config.yaml")
@click.option('--evb', required = False, help = "Path to the EVB file. Ignore if mentioned in config.yaml. Otherwise the filepath will be overwritten")
@click.option('--workers', '-w', required = False, default = None, type = int, help = " Number of parallel workers. Default value : cpu_count - 1")

@click.option("--json-dir", default = "OBS_INFO", show_default = True, help = "Directory containing the json metadata files")
@click.option("--no-dl2", is_flag = True, default = False, help = "Skip Hillas parametrization. Use for processing calibration runs")

@click.pass_context

def process(ctx, config, evb, output_dir, json_dir, no_dl2, workers ):
    steps = []
    # Extraction
    steps.append("extract")
    # H5 creation
    steps.append("createH5")

    click.echo(click.style("\nExtracting Events from EVB...", bold = True))
    ctx.invoke(extract, evb = evb, config = config, workers = workers)
    if no_dl2:
        click.echo(click.style("\nWriting DL1...\nSkipping Hillas Parametrization", bold = True))
    else:
        click.echo(click.style("\nWriting DL1 Images and Parameters...", bold = True))
    processed_files, skipped, failed = ctx.invoke(createh5, output_dir = output_dir, json_dir = json_dir, no_dl2 = no_dl2, config = config)
    click.echo(click.style("\nPipeline execution complete", fg = "green", bold = True))
    if processed_files:
        click.echo(click.style("Processed:", fg = "green"))
        for name in processed_files:
            click.echo(click.style(f"  - {name}", fg = "green"))
    if skipped:
        click.echo(click.style(f"Skipped (missing JSON): {', '.join(skipped)}", fg = "yellow"))
    if failed:
        click.echo(click.style("Failed:", fg = "red"))
        for name, reason in failed.items():
            click.echo(click.style(f"  - {name}: {reason}", fg = "red"))

# Read-Eval-Print Loop to run multiple commands 

def repl():
    '''
        Prints the ASCII banner and a help prompt. Reads lines from stdin with
        readline history (stored in ~/.sipm_history, last 500 commands). Each line is
        split with shlex and dispatched to cli.main in standalone_mode=False. Handles
        ClickException, Abort, SystemExit, and generic exceptions without terminating
        the session. Exits on 'exit', 'quit', EOF, or KeyboardInterrupt.

    '''
    import readline
    import atexit

    history_file = Path.home() / ".sipm_history"

    # Load previous session's history
    if history_file.exists():
        readline.read_history_file(history_file)

    readline.set_history_length(500)   # keep last 500 commands

    # Save history when the session ends
    atexit.register(readline.write_history_file, history_file)

    
    click.echo(banner)
    click.echo(click.style("Type 'help' for available commands. Type 'exit' to quit" ))

    while True:
        try:
            raw = input(click.style("scicam: ", fg = 'blue', bold = True)).strip()

            if not raw:
                continue

            if raw.lower() in ('exit', 'quit'):
                click.echo(click.style("Exiting", fg = 'red'))
                break

            if raw.lower() in ('help', '--help'):
                with click.Context(cli) as ctx:
                    click.echo(cli.get_help(ctx))
                continue

            import shlex

            args = shlex.split(raw)
            try:
                cli.main(args = args, standalone_mode = False)
            except click.ClickException as e:
                e.show()
            except click.exceptions.Abort:
                click.echo("\nAborted")
            except SystemExit:
                pass
            except Exception as e:
                click.echo(click.style(f"Error: {e}", fg = 'red'))
        except (KeyboardInterrupt, EOFError):
            click.echo(click.style("\nExiting"), fg = 'red')
# Initialization

def main():
    '''
        If no command-line arguments are provided (sys.argv has length 1), launches
        the interactive REPL. Otherwise hands control directly to the Click CLI group,
        enabling the script to function as both an interactive shell and a standard
        command-line tool.

    '''
    if len(sys.argv) == 1: #If no argument entered go to interactive mode
        repl()
    else:
        try:
            cli()
        except click.ClickException as e:
            e.show()
            sys.exit(1)
        except Exception as e:
            click.echo(click.style(f"Error: {e}", fg = 'red'))
            sys.exit(1)

if __name__ == "__main__":
    main()

