import os


if "QT_API" not in os.environ:
    os.environ["QT_API"] = "pyside2"

PROGRAM_NAME = "Minecraft Modpack Builder"
