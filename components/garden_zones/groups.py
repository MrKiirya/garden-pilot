# garden_zones — groups, zones and lane codegen (new file, not part of upstream ESPHome).
# Copyright (c) GardenPilot contributors.
# Licensed under the GNU General Public License v3, like ESPHome's C++ runtime; see LICENSE in this directory.
#
# Imported by __init__.py (region `groups`) and by components/garden_zone/__init__.py. The lane assignment itself is
# in lane_plan.py (pure Python); the runtime group object is in group.h.

import logging

from esphome import automation
from esphome.automation import maybe_simple_id
import esphome.codegen as cg
from esphome.components import garden_zones as gz
from esphome.components import number, switch
import esphome.config_validation as cv
from esphome.const import (
    CONF_ID,
    CONF_INITIAL_VALUE,
    CONF_MAX_VALUE,
    CONF_MIN_VALUE,
    CONF_NAME,
    CONF_RESTORE_VALUE,
    CONF_RUN_DURATION,
    CONF_SET_ACTION,
    CONF_STEP,
)
from esphome.core import CORE, ID
from esphome.helpers import fnv1_hash

from .lane_plan import LanePlanError, plan_lanes

_LOGGER = logging.getLogger(__name__)

CONF_GROUP = "group"
CONF_GROUPS = "groups"
CONF_LANE = "lane"
CONF_MAX_PARALLEL = "max_parallel"
CONF_ZONES = "zones"
CONF_ZONE_NUMBER = "zone_number"
ZONE_KEY = "garden_zone"

group_ns = gz.sprinkler_ns
GardenZonesGroup = group_ns.class_("GardenZonesGroup", cg.Component)
QueueZoneAction = group_ns.class_("QueueZoneAction", automation.Action)
RemoveQueuedZoneAction = group_ns.class_("RemoveQueuedZoneAction", automation.Action)
RunZoneAction = group_ns.class_("RunZoneAction", automation.Action)
StartGroupQueueAction = group_ns.class_("StartGroupQueueAction", automation.Action)
StartGroupCycleAction = group_ns.class_("StartGroupCycleAction", automation.Action)
ShutdownGroupAction = group_ns.class_("ShutdownGroupAction", automation.Action)
IsZoneQueuedCondition = group_ns.class_("IsZoneQueuedCondition", automation.Condition)

# the zone schema is the stock valve schema without the per-valve pump (the pump belongs to the group)
_ZONE_EXCLUDED = {gz.CONF_PUMP_SWITCH_ID, gz.CONF_VALVE_SWITCH_ID}
_zone_base = {
    key: value
    for key, value in gz.SPRINKLER_VALVE_SCHEMA.schema.items()
    if str(key) not in _ZONE_EXCLUDED
}

ZONE_SCHEMA = cv.Schema(
    {
        **_zone_base,
        cv.Required(CONF_GROUP): cv.use_id(GardenZonesGroup),
        cv.Required(gz.CONF_VALVE_SWITCH_ID): cv.use_id(switch.Switch),
        cv.Optional(CONF_LANE): cv.int_range(min=0),
    }
)


def _validate_zone(zone):
    has_duration = CONF_RUN_DURATION in zone
    has_number = gz.CONF_RUN_DURATION_NUMBER in zone
    if not has_duration and not has_number:
        raise cv.Invalid(
            f"Either {CONF_RUN_DURATION} or {gz.CONF_RUN_DURATION_NUMBER} must be specified for each zone"
        )
    if has_duration and has_number:
        raise cv.Invalid(
            f"Do not specify {CONF_RUN_DURATION} when using {gz.CONF_RUN_DURATION_NUMBER}; "
            f"use number component's {CONF_INITIAL_VALUE} instead"
        )
    return zone


ZONE_SCHEMA = cv.All(ZONE_SCHEMA, _validate_zone)


def _max_parallel(value):
    if isinstance(value, str) and value.strip().lower() == "all":
        return "all"
    return cv.positive_int(value)


GROUP_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_ID): cv.declare_id(GardenZonesGroup),
        cv.Optional(CONF_NAME): cv.string,
        cv.Required(CONF_MAX_PARALLEL): _max_parallel,
        cv.Optional(gz.CONF_PUMP_SWITCH_ID): cv.use_id(switch.Switch),
        cv.Exclusive(
            gz.CONF_PUMP_START_PUMP_DELAY, "pump_start_xxxx_delay"
        ): cv.positive_time_period_seconds,
        cv.Exclusive(
            gz.CONF_PUMP_STOP_PUMP_DELAY, "pump_stop_xxxx_delay"
        ): cv.positive_time_period_seconds,
        cv.Exclusive(
            gz.CONF_PUMP_START_VALVE_DELAY, "pump_start_xxxx_delay"
        ): cv.positive_time_period_seconds,
        cv.Exclusive(
            gz.CONF_PUMP_STOP_VALVE_DELAY, "pump_stop_xxxx_delay"
        ): cv.positive_time_period_seconds,
        cv.Optional(gz.CONF_PERSIST_QUEUE, default=True): cv.boolean,
    }
).extend(cv.COMPONENT_SCHEMA)

GROUPS_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_GROUPS): cv.ensure_list(GROUP_SCHEMA),
        cv.Optional(CONF_ZONES, default=[]): cv.ensure_list(ZONE_SCHEMA),
    }
)


def lane_id_name(group_id, lane_index):
    return f"{group_id}_lane_{lane_index}"


def is_groups_form(value):
    return isinstance(value, dict) and (CONF_GROUPS in value or CONF_ZONES in value)


def _group_name(group):
    return group.get(CONF_NAME, group[CONF_ID].id)


def zones_by_group(config, zone_entries):
    """Zone configs per group id, in zone order: inline `zones:` first, then `garden_zone:` entries."""
    result = {group[CONF_ID].id: [] for group in config[CONF_GROUPS]}
    for zone in [*config.get(CONF_ZONES, []), *zone_entries]:
        result.setdefault(zone[CONF_GROUP].id, []).append(zone)
    return result


def plan_group(group, zones):
    try:
        plan = plan_lanes(
            _group_name(group),
            group[CONF_MAX_PARALLEL],
            [zone.get(CONF_LANE) for zone in zones],
        )
    except LanePlanError as err:
        raise cv.Invalid(str(err)) from err
    limit = group[CONF_MAX_PARALLEL]
    if isinstance(limit, int) and any(zone.get(CONF_LANE) is not None for zone in zones) and len(plan) < limit:
        _LOGGER.info(
            "garden_zones group '%s': %d of %d pinned lanes have no zones and are not generated; "
            "the remaining lanes are renumbered",
            _group_name(group),
            limit - len(plan),
            limit,
        )
    return plan


def final_validate_groups(config):
    """Cross-zone rules over inline zones and `garden_zone:` entries; see tasks/012."""
    import esphome.final_validate as fv

    full = fv.full_config.get()
    entries = full.get(ZONE_KEY, []) or []
    if not isinstance(config, dict):
        # list form (stock controllers): garden_zone: entries cannot reference a group there; their `group:`
        # use_id check fails first with "doesn't inherit from GardenZonesGroup"
        return config
    by_group = zones_by_group(config, entries)
    valves = {}
    pump_owner = {}
    declared = {declared_id.id for declared_id, _ in full.declare_ids}
    for group in config[CONF_GROUPS]:
        zones = by_group[group[CONF_ID].id]
        name = _group_name(group)
        if not zones:
            raise cv.Invalid(f"group '{name}' has no zones")
        plan = plan_group(group, zones)
        for lane_index in range(len(plan)):
            lane_name = lane_id_name(group[CONF_ID].id, lane_index)
            if lane_name in declared:
                raise cv.Invalid(
                    f"the generated lane id '{lane_name}' of group '{name}' clashes with an id declared elsewhere; "
                    "rename the group or the other id"
                )
            declared.add(lane_name)
            # Lane controllers are generated components. They must be known before the core `to_code` emits
            # ESPHOME_COMPONENT_COUNT, so they are declared here (final validation runs before any `to_code`).
            CORE.component_ids.add(lane_name)
        if gz.CONF_PUMP_SWITCH_ID in group:
            pump = group[gz.CONF_PUMP_SWITCH_ID].id
            if pump in pump_owner:
                raise cv.Invalid(
                    f"pump switch '{pump}' is used by groups '{pump_owner[pump]}' and '{name}'; "
                    "a pump can belong to one group only"
                )
            pump_owner[pump] = name
        for zone in zones:
            valve = zone[gz.CONF_VALVE_SWITCH_ID].id
            if valve in valves:
                raise cv.Invalid(
                    f"valve_switch_id '{valve}' is used by two zones (groups '{valves[valve]}' and '{name}')"
                )
            valves[valve] = name
    for pump, owner in pump_owner.items():
        if pump in valves:
            raise cv.Invalid(
                f"pump switch '{pump}' of group '{owner}' is also the valve switch of a zone"
            )
    return config


# ------------------------------------------------------------------------------------------------ actions

_GROUP_ID = {cv.GenerateID(): cv.use_id(GardenZonesGroup)}

GROUP_ACTION_SCHEMA = maybe_simple_id({cv.Required(CONF_ID): cv.use_id(GardenZonesGroup)})

ZONE_NUMBER_SCHEMA = cv.maybe_simple_value(
    {
        **_GROUP_ID,
        cv.Required(CONF_ZONE_NUMBER): cv.templatable(cv.positive_int),
    },
    key=CONF_ZONE_NUMBER,
)

ZONE_RUN_SCHEMA = cv.maybe_simple_value(
    {
        **_GROUP_ID,
        cv.Required(CONF_ZONE_NUMBER): cv.templatable(cv.positive_int),
        cv.Optional(CONF_RUN_DURATION): cv.templatable(cv.positive_time_period_seconds),
    },
    key=CONF_ZONE_NUMBER,
)


@automation.register_action(
    "garden_zones.queue_zone", QueueZoneAction, ZONE_RUN_SCHEMA, synchronous=True
)
async def queue_zone_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    template_ = await cg.templatable(config[CONF_ZONE_NUMBER], args, cg.size_t)
    cg.add(var.set_zone_number(template_))
    if CONF_RUN_DURATION in config:
        template_ = await cg.templatable(config[CONF_RUN_DURATION], args, cg.uint32)
        cg.add(var.set_zone_run_duration(template_))
    return var


@automation.register_action(
    "garden_zones.run_zone", RunZoneAction, ZONE_RUN_SCHEMA, synchronous=True
)
async def run_zone_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    template_ = await cg.templatable(config[CONF_ZONE_NUMBER], args, cg.size_t)
    cg.add(var.set_zone_number(template_))
    if CONF_RUN_DURATION in config:
        template_ = await cg.templatable(config[CONF_RUN_DURATION], args, cg.uint32)
        cg.add(var.set_zone_run_duration(template_))
    return var


@automation.register_action(
    "garden_zones.remove_queued_zone",
    RemoveQueuedZoneAction,
    ZONE_NUMBER_SCHEMA,
    synchronous=True,
)
async def remove_queued_zone_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, paren)
    template_ = await cg.templatable(config[CONF_ZONE_NUMBER], args, cg.size_t)
    cg.add(var.set_zone_number(template_))
    return var


@automation.register_condition(
    "garden_zones.is_zone_queued", IsZoneQueuedCondition, ZONE_NUMBER_SCHEMA
)
async def is_zone_queued_to_code(config, condition_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(condition_id, template_arg, paren)
    template_ = await cg.templatable(config[CONF_ZONE_NUMBER], args, cg.size_t)
    cg.add(var.set_zone_number(template_))
    return var


@automation.register_action(
    "garden_zones.start_group_queue",
    StartGroupQueueAction,
    GROUP_ACTION_SCHEMA,
    synchronous=True,
)
@automation.register_action(
    "garden_zones.start_group_cycle",
    StartGroupCycleAction,
    GROUP_ACTION_SCHEMA,
    synchronous=True,
)
@automation.register_action(
    "garden_zones.shutdown_group",
    ShutdownGroupAction,
    GROUP_ACTION_SCHEMA,
    synchronous=True,
)
async def group_simple_action_to_code(config, action_id, template_arg, args):
    paren = await cg.get_variable(config[CONF_ID])
    return cg.new_Pvariable(action_id, template_arg, paren)


# ------------------------------------------------------------------------------------------------ codegen


async def _new_number(conf):
    var = await number.new_number(
        conf,
        min_value=conf[CONF_MIN_VALUE],
        max_value=conf[CONF_MAX_VALUE],
        step=conf[CONF_STEP],
    )
    await cg.register_component(var, conf)
    cg.add(var.set_initial_value(conf[CONF_INITIAL_VALUE]))
    cg.add(var.set_restore_value(conf[CONF_RESTORE_VALUE]))
    if CONF_SET_ACTION in conf:
        await automation.build_automation(
            var.get_set_trigger(), [(float, "x")], conf[CONF_SET_ACTION]
        )
    return var


async def to_code_groups(config):
    by_group = zones_by_group(config, CORE.config.get(ZONE_KEY, []) or [])
    all_lanes = []
    for group in config[CONF_GROUPS]:
        gid = group[CONF_ID].id
        name = _group_name(group)
        zones = by_group[gid]
        plan = plan_group(group, zones)
        group_var = cg.new_Pvariable(group[CONF_ID], name)
        await cg.register_component(group_var, group)

        zone_table = {}
        pump = None
        if gz.CONF_PUMP_SWITCH_ID in group:
            pump = await cg.get_variable(group[gz.CONF_PUMP_SWITCH_ID])

        for lane_index, lane_zones in enumerate(plan):
            # the id is added to CORE.component_ids during final validation (see final_validate_groups)
            lane_id = ID(lane_id_name(gid, lane_index), is_declaration=True, type=gz.Sprinkler)
            lane = cg.new_Pvariable(lane_id, f"{name} lane {lane_index}")
            await cg.register_component(lane, {})
            cg.add(lane.set_lane_mode(True))
            all_lanes.append(lane)
            cg.add(group_var.add_lane(lane))

            cg.add(lane.set_persist_queue(group[gz.CONF_PERSIST_QUEUE]))
            valve_ids = ",".join(zones[z][gz.CONF_VALVE_SWITCH_ID].id for z in lane_zones)
            cg.add(
                lane.set_queue_pref_key(
                    fnv1_hash(f"garden_zones_queue:{lane_id.id}:{valve_ids}")
                )
            )

            for key, setter in (
                (gz.CONF_PUMP_START_PUMP_DELAY, "set_pump_start_delay"),
                (gz.CONF_PUMP_STOP_PUMP_DELAY, "set_pump_stop_delay"),
                (gz.CONF_PUMP_START_VALVE_DELAY, "set_valve_start_delay"),
                (gz.CONF_PUMP_STOP_VALVE_DELAY, "set_valve_stop_delay"),
            ):
                if key in group:
                    cg.add(getattr(lane, setter)(group[key]))

            for valve_index, zone_number in enumerate(lane_zones):
                zone = zones[zone_number]
                zone_table[zone_number] = (lane_index, valve_index)

                sw_valve = await switch.new_switch(zone[gz.CONF_VALVE_SWITCH])
                await cg.register_component(sw_valve, zone[gz.CONF_VALVE_SWITCH])
                if gz.CONF_ENABLE_SWITCH in zone:
                    sw_enable = await switch.new_switch(zone[gz.CONF_ENABLE_SWITCH])
                    await cg.register_component(sw_enable, zone[gz.CONF_ENABLE_SWITCH])
                    cg.add(lane.add_valve(sw_valve, sw_enable))
                else:
                    cg.add(lane.add_valve(sw_valve))

                duration = zone.get(CONF_RUN_DURATION)
                if duration is None:
                    duration = zone[gz.CONF_RUN_DURATION_NUMBER][CONF_INITIAL_VALUE]
                raw = await cg.get_variable(zone[gz.CONF_VALVE_SWITCH_ID])
                cg.add(lane.configure_valve_switch(valve_index, raw, duration))
                if pump is not None:
                    cg.add(lane.configure_valve_pump_switch(valve_index, pump))
                if gz.CONF_RUN_DURATION_NUMBER in zone:
                    num = await _new_number(zone[gz.CONF_RUN_DURATION_NUMBER])
                    cg.add(lane.configure_valve_run_duration_number(valve_index, num))

        for zone_number in range(len(zones)):
            lane_index, valve_index = zone_table[zone_number]
            cg.add(group_var.add_zone(lane_index, valve_index))

    for lane in all_lanes:
        for other in all_lanes:
            if other is not lane:
                cg.add(lane.add_controller(other))
