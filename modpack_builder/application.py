import os
import sys
import base64
import binascii

from pathlib import Path

import markdown2

os.environ["QT_API"] = "pyqt5"

from qtpy.QtWidgets import QApplication, QMainWindow
from qtpy.QtWebEngineWidgets import QWebEnginePage
from qtpy.QtGui import QDesktopServices, QPixmap
from qtpy import QtCore
from qtpy import uic

from . import helpers

from .builder2 import ModpackBuilder
from .multi_progress_dialog import MultiProgressDialog


class LockedWebEnginePage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationTypeTyped:
            return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        QDesktopServices.openUrl(url)
        return False


class ModpackBuilderWindow(QMainWindow):
    __should_reset_profile_icon_path = False
    
    def __init__(self, builder, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.builder = builder

        uic.loadUi(str((Path(__file__).parent / "ui/modpack_builder_window.ui").resolve()), self)

        # Fix for PyQt5
        if os.environ["QT_API"] == "pyqt5":
            self.setContentsMargins(9, 9, 9, 9)

        # Set up the QWebEngineView for the markdown information view
        self.information_tab_frame.layout().setContentsMargins(0, 0, 0, 0)
        self.information_web_engine_page = LockedWebEnginePage()
        self.information_web_engine_view.setPage(self.information_web_engine_page)
        self.information_web_engine_view.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
        self.information_web_engine_view.setZoomFactor(0.75)

        self.__bind_spin_boxes_and_sliders()
        self.__set_spin_box_and_slider_ranges()
        self.__bind_file_and_directory_picker_buttons()

    def __bind_spin_boxes_and_sliders(self):
        @helpers.make_slot(float)
        @helpers.connect_slot(self.allocated_memory_spin_box.valueChanged)
        def __on_allocated_memory_spin_box_value_changed(value):
            self.allocated_memory_slider.setValue(int(value * 2))
            self.builder.java_runtime_memory = value * 1024

        @helpers.make_slot(int)
        @helpers.connect_slot(self.allocated_memory_slider.valueChanged)
        def __on_allocated_memory_slider_value_changed(value):
            self.allocated_memory_spin_box.setValue(int(value / 2))

        @helpers.make_slot(int)
        @helpers.connect_slot(self.concurrent_requests_spin_box.valueChanged)
        def __on_concurrent_requests_spin_box_value_changed(value):
            self.builder.concurrent_requests = value

        @helpers.make_slot(int)
        @helpers.connect_slot(self.concurrent_downloads_spin_box.valueChanged)
        def __on_concurrent_downloads_spin_box_value_changed(value):
            self.builder.concurrent_downloads = value

    def __set_spin_box_and_slider_ranges(self):
        # Set the min and max range for concurrent requests and downloads sliders/spin boxes
        self.concurrent_requests_spin_box.setRange(1, ModpackBuilder._max_concurrent_requests)
        self.concurrent_requests_slider.setRange(1, ModpackBuilder._max_concurrent_requests)
        self.concurrent_downloads_spin_box.setRange(1, ModpackBuilder._max_concurrent_downloads)
        self.concurrent_downloads_slider.setRange(1, ModpackBuilder._max_concurrent_downloads)

        # Set the min and max range for the Java runtime allocated memory slider and spin box
        max_recommended_memory = ModpackBuilder._get_max_recommended_memory()
        self.allocated_memory_spin_box.setRange(1, max_recommended_memory)
        self.allocated_memory_slider.setRange(2, max_recommended_memory * 2)

    def __bind_file_and_directory_picker_buttons(self):
        @helpers.make_slot()
        @helpers.connect_slot(self.modpack_package_select_button.clicked)
        def __on_modpack_package_select_button_clicked():
            modpack_package_path = helpers.pick_file(
                parent=self,
                title="Select Modpack Package",
                path=Path(self.modpack_package_line_edit.text()),
                types=("Zip Archive (*.zip)",)
            ).resolve()

            self.modpack_package_line_edit.setText(str(modpack_package_path))
            self.__load_package(modpack_package_path)


        @helpers.make_slot()
        @helpers.connect_slot(self.profile_icon_path_select_button.clicked)
        def __on_profile_icon_path_select_button_clicked():
            profile_icon_path = helpers.pick_file(
                parent=self,
                title="Select Profile Icon",
                path=Path(self.profile_icon_path_line_edit.text()),
                types=("Portable Network Graphics (*.png)",)
            ).resolve()

            self.profile_icon_path_line_edit.setText(str(profile_icon_path))
            self.__should_reset_profile_icon_path = False

            with open(profile_icon_path, "rb") as image:
                self.profile_icon_base64_line_edit.setText(base64.b64encode(image.read()).decode())

        @helpers.make_slot()
        @helpers.connect_slot(self.minecraft_directory_select_button.clicked)
        def __on_minecraft_directory_select_button_clicked():
            minecraft_directory = helpers.pick_directory(
                parent=self,
                title="Select Minecraft Directory",
                path=Path(self.minecraft_directory_line_edit.text())
            ).resolve()

            self.minecraft_directory_line_edit.setText(str(minecraft_directory))

        @helpers.make_slot()
        @helpers.connect_slot(self.minecraft_launcher_select_button.clicked)
        def __on_minecraft_launcher_select_button_clicked():
            minecraft_launcher_path = helpers.pick_file(
                parent=self,
                title="Select Minecraft Launcher",
                path=Path(self.minecraft_launcher_line_edit.text()),
                types=("Executable Files (*.exe)",)
            ).resolve()

            self.minecraft_launcher_line_edit.setText(str(minecraft_launcher_path))

    def __bind_other_synchronized_line_edits(self):
        @helpers.make_slot(str)
        @helpers.connect_slot(self.profile_icon_base64_line_edit.textChanged)
        def __on_profile_icon_base64_line_edit_text_changed(text):
            try:
                qpixmap = QPixmap()
                qpixmap.loadFromData(base64.b64decode(text), "png")
                qpixmap = qpixmap.scaledToHeight(
                    self.profile_icon_image_label.contentsRect().height(),
                    QtCore.Qt.SmoothTransformation
                )
                self.profile_icon_image_label.setPixmap(qpixmap)
                self.builder.profile_icon_base64 = text
            except binascii.Error:
                pass

            if self.__should_reset_profile_icon_path:
                self.profile_icon_path_line_edit.setText("")

            self.__should_reset_profile_icon_path = True

    def __load_package(self, path):
        progress_dialog = MultiProgressDialog(parent=self)

        progress_dialog.setWindowTitle("Extracting Modpack Package")
        progress_dialog.main_reporter.text = f"Extracting {path.name}: %p%"

        self.builder.set_reporter(progress_dialog.main_reporter)
        self.builder.set_logger(progress_dialog.log)

        @helpers.make_slot()
        @helpers.connect_slot(progress_dialog.completed)
        def __on_progress_dialog_completed():
            self.__load_values_from_builder()
            progress_dialog.close()

        @helpers.make_thread(daemon=True)
        def __builder_load_package_thread():
            self.builder.load_package(path)
            progress_dialog.completed.emit()

        # @helpers.make_slot()
        # @helpers.connect_slot(progress_dialog.cancel_request)
        # def __on_cancel_request():
        #     progress_dialog.completed.emit()

        progress_dialog.show()
        __builder_load_package_thread.start()

    def __load_values_from_builder(self):
        self.show_information_markdown(self.builder.modpack_readme_path)

        # Set the value for concurrent requests and downloads spin boxes
        self.concurrent_requests_spin_box.setValue(self.builder.concurrent_requests)
        self.concurrent_downloads_spin_box.setValue(self.builder.concurrent_downloads)

        # Set default values
        self.allocated_memory_spin_box.setValue(self.builder.java_runtime_memory)
        self.minecraft_directory_line_edit.setText(str(self.builder.minecraft_directory))
        self.minecraft_launcher_line_edit.setText(str(self.builder.minecraft_launcher_path))

    def show_information_markdown(self, path):
        with open((Path(__file__).parent / "markdown.css").resolve(), "r", encoding="utf-8") as markdown_css_file:
            markdown_css = markdown_css_file.read()

        with open(path, "r", encoding="utf-8") as readme_file:
            readme_markdown = readme_file.read()

        readme_html = markdown2.markdown(
            readme_markdown,
            extras="cuddled-lists fenced-code-blocks smartypants spoiler strike tables tag-friendly task_list".split()
        )
        readme_html = f"""
        <html>
            <head>
                <style>
                    body {{
                        margin: 20px 30px;
                        user-select: none;
                    }}

                    {markdown_css}
                </style>
            </head>
            <body class='markdown-body'>
                {readme_html}
            </body>
        </html>
        """

        self.information_web_engine_page.setHtml(readme_html)


if __name__ == "__main__":
    app = QApplication([])
    builder = ModpackBuilder()
    window = ModpackBuilderWindow(builder)

    window.show()
    sys.exit(app.exec_())
