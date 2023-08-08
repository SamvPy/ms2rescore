"""Parse configuration from command line arguments and configuration files."""

import importlib.resources
import json
import multiprocessing as mp
from argparse import Namespace
from pathlib import Path
from typing import Dict, List, Union

import tomlkit
from cascade_config import CascadeConfig

from ms2rescore import package_data
from ms2rescore.exceptions import MS2RescoreConfigurationError


def _validate_filenames(config: Dict) -> Dict:
    """Validate and infer input/output filenames."""
    # psm_file should be provided
    if not config["ms2rescore"]["psm_file"]:
        raise MS2RescoreConfigurationError("`psm_file` should be provided.")

    # psm_file should exist
    id_file = Path(config["ms2rescore"]["psm_file"])
    if not id_file.is_file():
        raise FileNotFoundError(id_file)
    config["ms2rescore"]["psm_file"] = str(id_file)

    # spectrum_path should either be None, or existing path to file or dir
    if config["ms2rescore"]["spectrum_path"]:
        spectrum_path = Path(config["ms2rescore"]["spectrum_path"])
        if not spectrum_path.exists():
            raise FileNotFoundError(spectrum_path)
        config["ms2rescore"]["spectrum_path"] = str(spectrum_path)

    # Output filename should be None or its path should exist. If not, make path
    if config["ms2rescore"]["output_path"]:
        output_path = Path(config["ms2rescore"]["output_path"])
        if not output_path.is_dir():
            output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path(id_file).parent
    config["ms2rescore"]["output_path"] = str(output_path)

    return config


def _validate_processes(config: Dict) -> Dict:
    """Validate requested processes with available cpu count."""
    n_available = mp.cpu_count()
    if (config["ms2rescore"]["processes"] == -1) or (
        config["ms2rescore"]["processes"] > n_available
    ):
        config["ms2rescore"]["processes"] = n_available
    return config


def parse_configurations(configurations: List[Union[dict, str, Path, Namespace]]) -> Dict:
    """
    Parse and validate MS²Rescore configuration files and CLI arguments.

    Default configuration, user configuration files, and CLI/class arguments are parsed
    in cascading order, with each successive configuration taking priority over the
    previous.

    Parameters
    ----------
    configurations: Dict, str, Path, Namespace, List[Dict, str, Path, Namespace]
        configuration dictionary, path to configuration files, argparse Namespace, or a list of the
        above.
    """
    if not isinstance(configurations, list):
        configurations = [configurations]

    # Initialize CascadeConfig with validation schema and defaults
    config_schema = importlib.resources.open_text(package_data, "config_schema.json")
    config_default = importlib.resources.open_text(package_data, "config_default.json")
    cascade_conf = CascadeConfig(
        validation_schema=json.load(config_schema),
        none_overrides_value=False,
        max_recursion_depth=1,
    )
    cascade_conf.add_dict(json.load(config_default))

    # Add configurations
    for config in configurations:
        if isinstance(config, dict):
            cascade_conf.add_dict(config)
        elif isinstance(config, str) or isinstance(config, Path):
            if Path(config).suffix.lower() == ".json":
                cascade_conf.add_json(config)
            elif Path(config).suffix.lower() == ".toml":
                with open(config, "rt") as toml_file:
                    cascade_conf.add_dict(tomlkit.load(toml_file))
            else:
                raise MS2RescoreConfigurationError(
                    "Unknown file extension for configuration file. Should be `json` or " "`toml`."
                )
        elif isinstance(config, Namespace):
            cascade_conf.add_namespace(config, subkey="ms2rescore")
        else:
            raise ValueError(
                "Configuration should be a dictionary, argparse Namespace, or path to a "
                "configuration file."
            )

    # Parse configurations
    config = cascade_conf.parse()

    # Validate and infer filenames and number of parallel processes
    config = _validate_filenames(config)
    config = _validate_processes(config)

    # Convert feature_generators and rescoring_engine names to lowercase
    config["ms2rescore"]["feature_generators"] = {
        k.lower(): v for k, v in config["ms2rescore"]["feature_generators"].items()
    }
    config["ms2rescore"]["rescoring_engine"] = {
        k.lower(): v for k, v in config["ms2rescore"]["rescoring_engine"].items()
    }

    return config
