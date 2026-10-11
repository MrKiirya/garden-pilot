# garden_schedule_slot — one schedule slot of a garden_schedule hub, declared as a separate entry.
# Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
#
# Write the entry as a list item (`garden_schedule_slot: [- schedule: gh_schedule, slot: 1, ...]`): two dict-form
# entries from different packages would be merged into one slot by the package merge. Code generation is done by
# `garden_schedule`; the entities named here are plain ESPHome template entities (switch, datetime, text, number).

import esphome.config_validation as cv
from esphome.components import datetime, number, switch, text
from esphome.components.garden_schedule import (
    CONF_DAYS_IDS,
    CONF_ENABLED_ID,
    CONF_MULTIPLIER_ID,
    CONF_SCHEDULE,
    CONF_SLOT,
    CONF_START_ID,
    CONF_ZONES_ID,
    MAX_SLOTS,
    GardenSchedule,
)

DEPENDENCIES = ["garden_schedule"]
MULTI_CONF = True

CONFIG_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_SCHEDULE): cv.use_id(GardenSchedule),
        cv.Required(CONF_SLOT): cv.int_range(min=1, max=MAX_SLOTS),
        cv.Required(CONF_ENABLED_ID): cv.use_id(switch.Switch),
        cv.Required(CONF_START_ID): cv.use_id(datetime.TimeEntity),
        # Monday .. Sunday
        cv.Required(CONF_DAYS_IDS): cv.All(cv.ensure_list(cv.use_id(switch.Switch)), cv.Length(min=7, max=7)),
        cv.Required(CONF_ZONES_ID): cv.use_id(text.Text),
        cv.Required(CONF_MULTIPLIER_ID): cv.use_id(number.Number),
    }
)
