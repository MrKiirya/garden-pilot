# garden_schedule — device-side watering schedules: slots (start time, days, zones, multiplier) that fire from the clock.
# Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
#
# The hub (this file) is engine-agnostic: when a slot is due it fires `on_run` with (zone_mask, multiplier_pct, slot) and
# the YAML routes that to the gp_* layer. Slots are separate `garden_schedule_slot:` list items (schema only, see
# components/garden_schedule_slot/); the hub reads their entities and generates the registration code, like
# garden_zones does for garden_zone. Rules and entities: components/garden_schedule/README.md.

import logging

import esphome.codegen as cg
from esphome import automation
import esphome.config_validation as cv
from esphome.components import datetime, number, switch, text, text_sensor
from esphome.components import time as time_
from esphome.const import CONF_CONDITION, CONF_ID, CONF_TIME_ID, CONF_TRIGGER_ID
from esphome.core import CORE

AUTO_LOAD = ["switch", "number", "text", "text_sensor", "datetime", "time"]
CODEOWNERS = []
MULTI_CONF = True

_LOGGER = logging.getLogger(__name__)

CONF_CATCH_UP_WINDOW = "catch_up_window"
CONF_ZONE_COUNT = "zone_count"
CONF_ZONE_GROUP = "zone_group"
CONF_MASTER_SWITCH_ID = "master_switch_id"
CONF_NEXT_RUN_ID = "next_run_id"
CONF_NEXT_RUN_TEXT_ID = "next_run_text_id"
CONF_LAST_RESULT_ID = "last_result_id"
CONF_SKIP_IF = "skip_if"
CONF_REASON = "reason"
CONF_ON_RUN = "on_run"
CONF_ZONE = "zone"

# slot keys (shared with garden_schedule_slot)
CONF_SCHEDULE = "schedule"
CONF_SLOT = "slot"
CONF_ENABLED_ID = "enabled_id"
CONF_START_ID = "start_id"
CONF_DAYS_IDS = "days_ids"
CONF_ZONES_ID = "zones_id"
CONF_MULTIPLIER_ID = "multiplier_id"

MAX_SLOTS = 8
MAX_CATCH_UP_MINUTES = 6 * 60

garden_schedule_ns = cg.esphome_ns.namespace("garden_schedule")
GardenSchedule = garden_schedule_ns.class_("GardenSchedule", cg.Component)
RunTrigger = garden_schedule_ns.class_("RunTrigger", automation.Trigger.template(cg.uint32, cg.uint8, cg.uint8))
ZoneDoneAction = garden_schedule_ns.class_("ZoneDoneAction", automation.Action)
CancelPendingAction = garden_schedule_ns.class_("CancelPendingAction", automation.Action)


def _catch_up_window(value):
    value = cv.positive_time_period_minutes(value)
    if value.total_minutes > MAX_CATCH_UP_MINUTES:
        raise cv.Invalid(f"{CONF_CATCH_UP_WINDOW} must be at most 6 hours")
    return value


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(GardenSchedule),
        cv.Optional(CONF_TIME_ID): cv.use_id(time_.RealTimeClock),
        cv.Optional(CONF_CATCH_UP_WINDOW, default="60min"): _catch_up_window,
        # number of zones the zone lists may name; default: the number of gp_zone entries (else 16)
        cv.Optional(CONF_ZONE_COUNT): cv.int_range(min=1, max=32),
        # id of the gp group whose zones the lists name: the default zone count counts only its gp_zone entries
        cv.Optional(CONF_ZONE_GROUP): cv.string_strict,
        cv.Optional(CONF_MASTER_SWITCH_ID): cv.use_id(switch.Switch),
        cv.Optional(CONF_NEXT_RUN_ID): cv.use_id(text_sensor.TextSensor),
        cv.Optional(CONF_NEXT_RUN_TEXT_ID): cv.use_id(text_sensor.TextSensor),
        cv.Optional(CONF_LAST_RESULT_ID): cv.use_id(text_sensor.TextSensor),
        # a due slot is skipped (and marked for the day) when one of these conditions holds
        cv.Optional(CONF_SKIP_IF, default=[]): cv.ensure_list(
            cv.Schema(
                {
                    cv.Required(CONF_CONDITION): automation.validate_potentially_and_condition,
                    cv.Required(CONF_REASON): cv.string,
                }
            )
        ),
        cv.Optional(CONF_ON_RUN): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(RunTrigger)}
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


def check_slots(hub_id, slots):
    """Rules for the slots of one hub: at most MAX_SLOTS, unique slot numbers. `slots` = validated slot configs."""
    numbers = [slot[CONF_SLOT] for slot in slots if slot[CONF_SCHEDULE].id == hub_id]
    if len(numbers) > MAX_SLOTS:
        raise cv.Invalid(f"garden_schedule '{hub_id}': at most {MAX_SLOTS} slots, found {len(numbers)}")
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        raise cv.Invalid(f"garden_schedule '{hub_id}': duplicate slot number(s) {duplicates}")
    if not numbers:
        _LOGGER.warning("garden_schedule '%s' has no slots: nothing will run on a schedule", hub_id)
    return numbers


def _final_validate(config):
    import esphome.final_validate as fv

    full = fv.full_config.get()
    check_slots(config[CONF_ID].id, full.get("garden_schedule_slot", []) or [])
    return config


FINAL_VALIDATE_SCHEMA = _final_validate


async def to_code(config):
    hub = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(hub, config)
    cg.add(hub.set_key(str(config[CONF_ID])))
    time_id = config.get(CONF_TIME_ID)
    if time_id is None:  # the clock of the device: the first `time:` entry
        times = CORE.config.get("time") or []
        time_id = times[0].get(CONF_ID) if times else None
    if time_id is not None:
        cg.add(hub.set_time(await cg.get_variable(time_id)))
    cg.add(hub.set_catch_up_window(int(config[CONF_CATCH_UP_WINDOW].total_minutes)))
    zone_count = config.get(CONF_ZONE_COUNT)
    if zone_count is None:
        zones = CORE.config.get("gp_zone") or []
        group = config.get(CONF_ZONE_GROUP)
        if group is not None:
            zones = [z for z in zones if str(z.get("group")) == group]
        zone_count = len(zones) or 16
    cg.add(hub.set_zone_count(min(int(zone_count), 32)))
    if CONF_MASTER_SWITCH_ID in config:
        cg.add(hub.set_master_switch(await cg.get_variable(config[CONF_MASTER_SWITCH_ID])))
    if CONF_NEXT_RUN_ID in config:
        cg.add(hub.set_next_run_sensor(await cg.get_variable(config[CONF_NEXT_RUN_ID])))
    if CONF_NEXT_RUN_TEXT_ID in config:
        cg.add(hub.set_next_run_text_sensor(await cg.get_variable(config[CONF_NEXT_RUN_TEXT_ID])))
    if CONF_LAST_RESULT_ID in config:
        cg.add(hub.set_last_result_sensor(await cg.get_variable(config[CONF_LAST_RESULT_ID])))
    for skip in config[CONF_SKIP_IF]:
        condition = await automation.build_condition(skip[CONF_CONDITION], cg.TemplateArguments(), [])
        cg.add(hub.add_skip(condition, skip[CONF_REASON]))
    for slot in CORE.config.get("garden_schedule_slot") or []:
        if slot[CONF_SCHEDULE].id != config[CONF_ID].id:
            continue
        days = [await cg.get_variable(day) for day in slot[CONF_DAYS_IDS]]
        cg.add(
            hub.add_slot(
                slot[CONF_SLOT],
                await cg.get_variable(slot[CONF_ENABLED_ID]),
                await cg.get_variable(slot[CONF_START_ID]),
                await cg.get_variable(slot[CONF_ZONES_ID]),
                await cg.get_variable(slot[CONF_MULTIPLIER_ID]),
                cg.ArrayInitializer(*days),
            )
        )
    for conf in config.get(CONF_ON_RUN, []):
        trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], hub)
        await automation.build_automation(
            trigger, [(cg.uint32, "zone_mask"), (cg.uint8, "multiplier_pct"), (cg.uint8, "slot")], conf
        )


@automation.register_action(
    "garden_schedule.zone_done",
    ZoneDoneAction,
    cv.Schema(
        {
            cv.Required(CONF_ID): cv.use_id(GardenSchedule),
            cv.Required(CONF_ZONE): cv.templatable(cv.int_range(min=0, max=31)),
        }
    ),
    synchronous=True,
)
async def zone_done_to_code(config, action_id, template_arg, args):
    hub = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, hub)
    cg.add(var.set_zone(await cg.templatable(config[CONF_ZONE], args, cg.size_t)))
    return var


@automation.register_action(
    "garden_schedule.cancel_pending",
    CancelPendingAction,
    automation.maybe_simple_id({cv.Required(CONF_ID): cv.use_id(GardenSchedule)}),
    synchronous=True,
)
async def cancel_pending_to_code(config, action_id, template_arg, args):
    hub = await cg.get_variable(config[CONF_ID])
    return cg.new_Pvariable(action_id, template_arg, hub)
