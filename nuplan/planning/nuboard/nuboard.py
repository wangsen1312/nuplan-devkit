import logging
import os
import signal
from pathlib import Path
from typing import Any, List, Optional

import jinja2
from bokeh.application import Application
from bokeh.application.handlers import FunctionHandler
from bokeh.document.document import Document
from bokeh.server.server import Server
from tornado.ioloop import IOLoop
from tornado.web import StaticFileHandler

from nuplan.common.actor_state.vehicle_parameters import VehicleParameters
from nuplan.planning.nuboard.base.experiment_file_data import ExperimentFileData
from nuplan.planning.nuboard.tabs.configuration_tab import ConfigurationTab
from nuplan.planning.nuboard.tabs.histogram_tab import HistogramTab
from nuplan.planning.nuboard.tabs.overview_tab import OverviewTab
from nuplan.planning.nuboard.tabs.scenario_tab import ScenarioTab
from nuplan.planning.nuboard.utils.utils import check_nuboard_file_paths, read_nuboard_file_paths
from nuplan.planning.scenario_builder.abstract_scenario_builder import AbstractScenarioBuilder
from nuplan.planning.training.callbacks.profile_callback import ProfileCallback

logger = logging.getLogger(__name__)


class NuBoard:
    """NuBoard application class."""

    def __init__(
        self,
        nuboard_paths: List[str],
        scenario_builder: AbstractScenarioBuilder,
        vehicle_parameters: VehicleParameters,
        port_number: int = 5006,
        profiler_path: Optional[Path] = None,
        resource_prefix: Optional[str] = None,
    ):
        """
        Nuboard main class.
        :param nuboard_paths: A list of paths to nuboard files.
        :param scenario_builder: Scenario builder instance.
        :param vehicle_parameters: vehicle parameters.
        :param port_number: Bokeh port number.
        :param profiler_path: Path to save the profiler.
        :param resource_prefix: Prefix to the resource path in HTML.
        """
        self._profiler_path = profiler_path
        self._nuboard_paths = check_nuboard_file_paths(nuboard_paths)
        self._scenario_builder = scenario_builder
        self._port_number = port_number
        self._vehicle_parameters = vehicle_parameters
        self._doc: Optional[Document] = None
        self._resource_prefix = resource_prefix if resource_prefix else ""
        self._resource_path = Path(__file__).parents[0] / "resource"
        self._profiler_file_name = "nuboard"
        self._profiler: Optional[ProfileCallback] = None

    def stop_handler(self, sig: Any, frame: Any) -> None:
        """Helper to handle stop signals."""
        logger.info("Stopping the Bokeh application.")
        if self._profiler:
            self._profiler.save_profiler(self._profiler_file_name)
        IOLoop.current().stop()

    def run(self) -> None:
        """Run nuBoard WebApp."""
        logger.info(f"Opening Bokeh application on http://localhost:{self._port_number}/")

        io_loop = IOLoop.current()

        # Add stopping signal
        # TODO: Extract profiler to a more general interface
        if self._profiler_path is not None:
            signal.signal(signal.SIGTERM, self.stop_handler)
            signal.signal(signal.SIGINT, self.stop_handler)

            # Add profiler
            self._profiler = ProfileCallback(output_dir=self._profiler_path)
            self._profiler.start_profiler(self._profiler_file_name)

        bokeh_app = Application(FunctionHandler(self.main_page))
        server = Server(
            {"/": bokeh_app},
            io_loop=io_loop,
            port=self._port_number,
            extra_patterns=[(r"/resource/(.*)", StaticFileHandler, {"path": str(self._resource_path)})],
        )
        server.start()

        io_loop.add_callback(server.show, "/")
        # Catch RuntimeError in jupyter notebook
        try:
            io_loop.start()
        except RuntimeError as e:
            logger.warning(f"{e}")

    def main_page(self, doc: Document) -> None:
        """
        Main nuBoard page.
        :param doc: HTML document.
        """
        self._doc = doc
        template_path = Path(os.path.dirname(os.path.realpath(__file__))) / "templates"
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_path))
        self._doc.template = env.get_template("index.html")
        self._doc.title = "nuBoard"
        nuboard_files = read_nuboard_file_paths(file_paths=self._nuboard_paths)
        experiment_file_data = ExperimentFileData(file_paths=nuboard_files)
        overview_tab = OverviewTab(doc=self._doc, experiment_file_data=experiment_file_data)
        histogram_tab = HistogramTab(doc=self._doc, experiment_file_data=experiment_file_data)
        scenario_tab = ScenarioTab(
            experiment_file_data=experiment_file_data,
            scenario_builder=self._scenario_builder,
            doc=self._doc,
            vehicle_parameters=self._vehicle_parameters,
        )
        configuration_tab = ConfigurationTab(
            experiment_file_data=experiment_file_data, doc=self._doc, tabs=[overview_tab, histogram_tab, scenario_tab]
        )

        self._doc.add_root(configuration_tab.file_path_input)
        self._doc.add_root(configuration_tab.experiment_file_path_checkbox_group)

        self._doc.add_root(overview_tab.table)
        self._doc.add_root(overview_tab.planner_checkbox_group)

        self._doc.add_root(histogram_tab.scenario_type_multi_choice)
        self._doc.add_root(histogram_tab.metric_name_multi_choice)
        self._doc.add_root(histogram_tab.planner_checkbox_group)
        self._doc.add_root(histogram_tab.histogram_plots)
        self._doc.add_root(histogram_tab.bin_spinner)

        self._doc.add_root(scenario_tab.planner_checkbox_group)
        self._doc.add_root(scenario_tab.object_checkbox_group)
        self._doc.add_root(scenario_tab.traj_checkbox_group)
        self._doc.add_root(scenario_tab.map_checkbox_group)
        self._doc.add_root(scenario_tab.scalar_scenario_type_select)
        self._doc.add_root(scenario_tab.scalar_log_name_select)
        self._doc.add_root(scenario_tab.scalar_scenario_name_select)
        self._doc.add_root(scenario_tab.time_series_layout)
        self._doc.add_root(scenario_tab.scenario_score_layout)
        self._doc.add_root(scenario_tab.simulation_tile_layout)
