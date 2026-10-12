# garden_zone — one zone of a garden_zones group, declared as a separate entry.
# Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
#
# Write the entry as a list item (`garden_zone: [- group: ...]`): two dict-form entries from different packages are
# merged into one zone by ESPHome's package merge. Code generation is done by `garden_zones`.

from esphome.components.garden_zones import groups

DEPENDENCIES = ["garden_zones"]
MULTI_CONF = True

CONFIG_SCHEMA = groups.ZONE_SCHEMA
