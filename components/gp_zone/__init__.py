# gp_zone — the Home Assistant switch of one zone of a gp group ("Greenhouse bed 1": on = run, off = stop).
# Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
#
# One list item per bed (`gp_zone: [- group: gp_greenhouse, position: 1, name: ...]`): two dict-form entries from
# different packages would be merged into one switch by the package merge, so always write a list item.
# `position` is 1-based, the zone's number on screen; the gp group checks that the positions are exactly 1..N.

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import gp, switch

DEPENDENCIES = ["gp"]
MULTI_CONF = True

CONFIG_SCHEMA = (
    switch.switch_schema(gp.GpZoneSwitch, default_restore_mode="ALWAYS_OFF")
    .extend(
        {
            cv.Required(gp.CONF_GROUP): cv.use_id(gp.GpGroup),
            cv.Required(gp.CONF_POSITION): cv.int_range(min=1, max=16),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)


async def to_code(config):
    var = await switch.new_switch(config)
    await cg.register_component(var, config)
    cg.add(var.set_group(await cg.get_variable(config[gp.CONF_GROUP])))
    cg.add(var.set_zone(config[gp.CONF_POSITION] - 1))
