cmake_minimum_required(VERSION 3.16)

# Include BSP and project components
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(codex-passport)

