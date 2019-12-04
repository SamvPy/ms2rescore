#! python
# Standard library
import logging
import argparse
import sys
import subprocess
import os
import re
import json

# From package
import ms2rescore.setup_logging as setup_logging
import ms2rescore.rescore_core as rescore_core
import ms2rescore.maxquant_to_rescore as maxquant_to_rescore
import ms2rescore.parse_mgf as parse_mgf
import ms2rescore.msgf_to_rescore as msgf_to_rescore
import ms2rescore.tandem_to_rescore as tandem_to_rescore


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="MS²ReScore: Sensitive PSM rescoring with predicted MS²\
            peak intensities."
    )

    parser.add_argument(
        "identification_file", help="Path to identification file (mzid,\
            msms.txt, tandem xml)"
    )

    parser.add_argument(
        "-m", metavar="FILE", action="store", dest="mgf_file",
        help="Path to MGF file (default: derived from identifications file).\
            Not applicable to MaxQuant pipeline."
    )

    parser.add_argument(
        "-c", metavar="FILE", action="store", dest="config_file",
        default="config.json", help="Path to JSON MS²ReScore configuration\
            file. See README.md for more info. (default: config.json)"
    )

    parser.add_argument(
        "-o", metavar="FILE", action="store", dest="output_filename",
        help="Name for output files (default: derive from identification file")

    parser.add_argument(
        "-l", metavar="LEVEL", action="store", dest="log_level",
        default="info", help="Logging level (default: `info`)")

    return parser.parse_args()


def parse_config():
    """
    Parse config file, merge with CLI arguments and check if input files exist.
    """

    args = parse_arguments()
    
    setup_logging.setup_logging(args.log_level)

    # Validate identification file
    if not os.path.isfile(args.identification_file):
        raise FileNotFoundError(args.identification_file)

    if args.mgf_file:
        if not os.path.isfile(args.mgf_file):
            raise FileNotFoundError(args.mgf_file)
    else:
        args.mgf_file = os.path.splitext(args.identification_file)[0] + '.mgf'

    if args.output_filename:
        output_path = os.path.abspath(args.output_filename)
        if not os.path.isdir(output_path):
            os.makedirs(output_path, exist_ok=True)
    else:
        args.output_filename = os.path.splitext(args.identification_file)[0]

    # Read config
    try:
        with open(args.config_file) as f:
            config = json.load(f)
    except json.decoder.JSONDecodeError:
        logging.critical("Could not read JSON config file. Please use correct \
            JSON formatting.")
        exit(1)

    # Add CLI arguments to config
    config['general']['identification_file'] = args.identification_file
    if args.mgf_file:
        config['general']['mgf_file'] = args.mgf_file
    if args.log_level:
        config['general']['log_level'] = args.log_level
    if args.output_filename:
        config['general']['output_filename'] = args.output_filename

    return config


def main():
    config = parse_config()

    # Check if Percolator is installed and callable
    if config['general']['run_percolator']:
        if subprocess.getstatusoutput('percolator -h')[0] != 0:
            logging.critical("Could not call Percolator. Install Percolator or\
                Set `run_percolator` to false")
            exit(1)

    # Check if MS2PIP is callable
    if subprocess.getstatusoutput('ms2pip -h')[0] != 0:
        logging.critical(
            "Could not call MS2PIP. Check that MS2PIP is set-up correctly.")
        exit(0)

    # Prepare with specific pipeline
    if config['general']['pipeline'].lower() == 'maxquant':
        logging.info("Using %s pipeline", config['general']['pipeline'])
        peprec_filename, mgf_filename = maxquant_to_rescore.maxquant_pipeline(config)
    elif config['general']['pipeline'].lower() in ['msgfplus', 'msgf+', 'ms-gf+']:
        peprec_filename, mgf_filename = msgf_to_rescore.msgf_pipeline(config)
    elif config['general']['pipeline'].lower() in ['tandem', 'xtandem', 'x!tandem']:
        peprec_filename, mgf_filename = tandem_to_rescore.tandem_pipeline(config)
    else:
        logging.critical("Could not recognize the requested pipeline.")
        exit(1)

    outname = config['general']['output_filename']

    # Run general MS2ReScore stuff
    ms2pip_config_filename = outname + '_ms2pip_config.txt'
    rescore_core.make_ms2pip_config(config, filename=ms2pip_config_filename)
    ms2pip_command = "ms2pip {} -c {} -s {} -m {}".format(
        peprec_filename,
        ms2pip_config_filename,
        mgf_filename,
        int(config["general"]["num_cpu"])
    )
    logging.info("Running MS2PIP: %s", ms2pip_command)
    subprocess.run(ms2pip_command, shell=True, check=True)

    logging.info("Calculating features from predicted spectra")
    preds_filename = peprec_filename.replace('.peprec', '') + "_" + \
        config["ms2pip"]["model"] + "_pred_and_emp.csv"
    rescore_core.calculate_features(
        preds_filename,
        outname + "_ms2pipfeatures.csv",
        int(config["general"]["num_cpu"]),
        show_progress_bar=config['general']['show_progress_bar']
    )

    logging.info("Generating PIN files")
    rescore_core.write_pin_files(
        outname + "_ms2pipfeatures.csv",
        peprec_filename, outname,
        feature_sets=config['general']['feature_sets']
    )

    if not config['general']['keep_tmp_files']:
        logging.debug("Removing temporary files")
        to_remove = [
            ms2pip_config_filename, preds_filename,
            outname + "_ms2pipfeatures.csv",
            outname + "_" + config['ms2pip']['model'] + "_correlations.csv",
            outname + '.mgf', outname + '.peprec'
        ]
        for filename in to_remove:
            try:
                os.remove(filename)
            except FileNotFoundError as e:
                logging.debug(e)

    # Run Percolator with different feature subsets
    if config['general']['run_percolator']:
        for subset in config['general']['feature_sets']:
            subname = outname + "_" + subset + "features"
            percolator_cmd = "percolator "
            for op in config["percolator"].keys():
                percolator_cmd = percolator_cmd + "--{} {} ".format(
                    op, config["percolator"][op]
                )
            percolator_cmd = percolator_cmd + "{} -m {} -M {} -w {} -v 0 -U --post-processing-tdc\n"\
                .format(
                    subname + ".pin", subname + ".pout",
                    subname + ".pout_dec", subname + ".weights"
                )

            logging.info("Running Percolator: %s", percolator_cmd)
            subprocess.run(percolator_cmd, shell=True)

            if not os.path.isfile(subname + ".pout"):
                logging.error("Error running Percolator")

    logging.info("MS2ReScore finished!")


if __name__ == "__main__":
    main()
