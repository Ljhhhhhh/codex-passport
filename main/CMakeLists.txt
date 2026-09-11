idf_component_register(
    SRCS "main.c"
         "passport_protocol.c"
         "passport_storage.c"
         "passport_ble.c"
         "passport_ui.c"
         "passport_idle.c"
         "passport_alert.c"
         "font_passport_16.c"
    INCLUDE_DIRS "."
    REQUIRES bsp nvs_flash bt
)
