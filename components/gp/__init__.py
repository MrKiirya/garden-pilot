# gp — the engine-neutral irrigation layer: per-zone read model, group summary, alerts and a fixed set of actions.
# Copyright (c) GardenPilot contributors. Licensed under the MIT licence of the repository (see LICENSE in the root).
#
# Contract and rules: components/gp/README.md. The hub (`gp:`) is declared once per device; every group names the engine
# it sits on with exactly one engine key (today `garden_zones_id`). The engine adapter lives with the engine
# (components/garden_zones/gp_engine.h); this component never includes it.

import esphome.codegen as cg
from esphome import automation
import esphome.config_validation as cv
from esphome.components import switch
from esphome.components import time as time_
from esphome.const import CONF_ID, CONF_NAME, CONF_TIME_ID, CONF_TRIGGER_ID
from esphome.core import CORE

AUTO_LOAD = ["switch", "time"]
CODEOWNERS = []

CONF_GROUPS = "groups"
CONF_KEY = "key"
CONF_GARDEN_ZONES_ID = "garden_zones_id"
CONF_ON_ALERT_CHANGE = "on_alert_change"
CONF_HUB = "hub"
CONF_GROUP = "group"
CONF_ZONE = "zone"
CONF_DURATION = "duration"
CONF_CLEAR_QUEUE = "clear_queue"
CONF_SEVERITY = "severity"
CONF_TEXT = "text"
CONF_SOURCE = "source"
CONF_POSITION = "position"

gp_ns = cg.esphome_ns.namespace("gp")
GpHub = gp_ns.class_("GpHub", cg.Component)
GpGroup = gp_ns.class_("GpGroup")
GpZoneSwitch = gp_ns.class_("GpZoneSwitch", switch.Switch, cg.Component)
Severity = gp_ns.enum("Severity", is_class=True)
Source = gp_ns.enum("Source", is_class=True)
AlertChangeTrigger = gp_ns.class_("AlertChangeTrigger", automation.Trigger.template())

# the engine group type is declared locally: this MIT component does not import the GPL engine's Python code
_GARDEN_ZONES_GROUP = cg.esphome_ns.namespace("garden_zones").class_("GardenZonesGroup", cg.Component)
ENGINE_KEYS = (CONF_GARDEN_ZONES_ID,)


def _engine_key(value):
    """Exactly one engine key per group; an unknown engine component is a config error."""
    value = cv.has_exactly_one_key(*ENGINE_KEYS)(value)
    return value


def _key(value):
    value = cv.string_strict(value)
    if not value or not all(c.islower() or c.isdigit() or c == "_" for c in value):
        raise cv.Invalid(f"group key '{value}' must be lowercase letters, digits and underscores")
    return value


def _group_schema():
    schema = {
        cv.Required(CONF_ID): cv.declare_id(GpGroup),
        cv.Required(CONF_NAME): cv.string,
        # the key addresses the group in the generic Home Assistant actions (`group: greenhouse`)
        cv.Optional(CONF_KEY): _key,
        cv.Optional(CONF_GARDEN_ZONES_ID): cv.use_id(_GARDEN_ZONES_GROUP),
    }
    return cv.All(cv.Schema(schema), _engine_key)


def _default_key(group):
    if CONF_KEY in group:
        return group[CONF_KEY]
    return "".join(c if c.isalnum() else "_" for c in group[CONF_NAME].lower())


CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(GpHub),
        cv.Optional(CONF_TIME_ID): cv.use_id(time_.RealTimeClock),
        cv.Optional(CONF_GROUPS, default=[]): cv.ensure_list(_group_schema()),
        cv.Optional(CONF_ON_ALERT_CHANGE): automation.validate_automation(
            {cv.GenerateID(CONF_TRIGGER_ID): cv.declare_id(AlertChangeTrigger)}
        ),
    }
).extend(cv.COMPONENT_SCHEMA)


def _final_validate(config):
    """Every zone of the engine group needs exactly one `gp_zone` (position 1..N) of the gp group."""
    import esphome.final_validate as fv

    full = fv.full_config.get()
    zone_items = full.get("gp_zone", []) or []
    garden_zones = full.get("garden_zone", []) or []
    for group in config[CONF_GROUPS]:
        engine = group[CONF_GARDEN_ZONES_ID].id
        count = sum(1 for zone in garden_zones if zone["group"].id == engine)
        positions = sorted(item[CONF_POSITION] for item in zone_items if item[CONF_GROUP].id == group[CONF_ID].id)
        if positions != list(range(1, count + 1)):
            raise cv.Invalid(
                f"gp group '{group[CONF_ID].id}': the gp_zone positions must be 1..{count} (one per zone of "
                f"garden_zones group '{engine}'), found {positions}"
            )
    return config


FINAL_VALIDATE_SCHEMA = _final_validate


async def to_code(config):
    hub = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(hub, config)
    time_id = config.get(CONF_TIME_ID)
    if time_id is None:  # the clock of the device: the first `time:` entry, if there is one
        times = CORE.config.get("time") or []
        time_id = times[0].get(CONF_ID) if times else None
    if time_id is not None:
        cg.add(hub.set_time(await cg.get_variable(time_id)))
    for group in config[CONF_GROUPS]:
        engine_group = await cg.get_variable(group[CONF_GARDEN_ZONES_ID])
        engine = cg.RawExpression(f"new esphome::garden_zones::GardenZonesEngine({engine_group})")
        var = cg.new_Pvariable(group[CONF_ID], _default_key(group), group[CONF_NAME], engine)
        cg.add(hub.add_group(var))
    for conf in config.get(CONF_ON_ALERT_CHANGE, []):
        trigger = cg.new_Pvariable(conf[CONF_TRIGGER_ID], hub)
        await automation.build_automation(trigger, [], conf)


# ------------------------------------------------------------------------------------------------ actions


def _target(extra=None, simple=CONF_ID):
    """Group actions address the group by `id` or, for the generic Home Assistant actions, by `hub` + `group` text."""
    fields = {
        cv.Optional(CONF_ID): cv.use_id(GpGroup),
        cv.Optional(CONF_HUB): cv.use_id(GpHub),
        cv.Optional(CONF_GROUP): cv.templatable(cv.string),
    }
    fields.update(extra or {})

    def validate(config):
        cv.has_exactly_one_key(CONF_ID, CONF_HUB)(config)
        if CONF_HUB in config and CONF_GROUP not in config:
            raise cv.Invalid("'hub' needs 'group' (the group key)")
        if CONF_ID in config and CONF_GROUP in config:
            raise cv.Invalid("'group' is only used together with 'hub'")
        return config

    schema = cv.All(cv.Schema(fields), validate)

    def simple_or_dict(value):
        # `gp.stop_all: gp_greenhouse` is the short form of `{id: gp_greenhouse}`
        return schema(value if isinstance(value, dict) else {simple: value})

    return simple_or_dict


async def _new_action(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    if CONF_ID in config:
        cg.add(var.set_group(await cg.get_variable(config[CONF_ID])))
    else:
        cg.add(var.set_hub(await cg.get_variable(config[CONF_HUB])))
        cg.add(var.set_group_key(await cg.templatable(config[CONF_GROUP], args, cg.std_string)))
    return var


def _register_group_action(name, cls, extra=None):
    def decorate(fn):
        return automation.register_action(name, cls, _target(extra), synchronous=True)(fn)

    return decorate


RunZoneAction = gp_ns.class_("RunZoneAction", automation.Action)
EnqueueZoneAction = gp_ns.class_("EnqueueZoneAction", automation.Action)
DequeueZoneAction = gp_ns.class_("DequeueZoneAction", automation.Action)
StartQueueAction = gp_ns.class_("StartQueueAction", automation.Action)
FullCycleAction = gp_ns.class_("FullCycleAction", automation.Action)
StopAllAction = gp_ns.class_("StopAllAction", automation.Action)
InhibitAction = gp_ns.class_("InhibitAction", automation.Action)
ResetWatchdogAction = gp_ns.class_("ResetWatchdogAction", automation.Action)
AlertRaiseAction = gp_ns.class_("AlertRaiseAction", automation.Action)
AlertClearAction = gp_ns.class_("AlertClearAction", automation.Action)
ZoneRunningCondition = gp_ns.class_("ZoneRunningCondition", automation.Condition)
AnyRunningCondition = gp_ns.class_("AnyRunningCondition", automation.Condition)
WatchdogTrippedCondition = gp_ns.class_("WatchdogTrippedCondition", automation.Condition)
AlertActiveCondition = gp_ns.class_("AlertActiveCondition", automation.Condition)

_ZONE = {cv.Required(CONF_ZONE): cv.templatable(cv.positive_int)}
_DURATION = {cv.Optional(CONF_DURATION): cv.templatable(cv.positive_time_period_seconds)}


@automation.register_action(
    "gp.run_zone",
    RunZoneAction,
    _target({**_ZONE, **_DURATION, cv.Optional(CONF_SOURCE, default="manual"): cv.one_of("manual", "service", lower=True)}),
    synchronous=True,
)
async def run_zone_to_code(config, action_id, template_arg, args):
    var = await _new_action(config, action_id, template_arg, args)
    cg.add(var.set_zone(await cg.templatable(config[CONF_ZONE], args, cg.size_t)))
    if CONF_DURATION in config:
        cg.add(var.set_duration(await cg.templatable(config[CONF_DURATION], args, cg.uint32)))
    cg.add(var.set_source(getattr(Source, config[CONF_SOURCE].upper())))
    return var


@automation.register_action(
    "gp.enqueue_zone", EnqueueZoneAction, _target({**_ZONE, **_DURATION}), synchronous=True
)
async def enqueue_zone_to_code(config, action_id, template_arg, args):
    var = await _new_action(config, action_id, template_arg, args)
    cg.add(var.set_zone(await cg.templatable(config[CONF_ZONE], args, cg.size_t)))
    if CONF_DURATION in config:
        cg.add(var.set_duration(await cg.templatable(config[CONF_DURATION], args, cg.uint32)))
    return var


@automation.register_action("gp.dequeue_zone", DequeueZoneAction, _target(_ZONE), synchronous=True)
async def dequeue_zone_to_code(config, action_id, template_arg, args):
    var = await _new_action(config, action_id, template_arg, args)
    cg.add(var.set_zone(await cg.templatable(config[CONF_ZONE], args, cg.size_t)))
    return var


@automation.register_action(
    "gp.inhibit", InhibitAction, _target({cv.Required("state"): cv.templatable(cv.boolean)}), synchronous=True
)
async def inhibit_to_code(config, action_id, template_arg, args):
    var = await _new_action(config, action_id, template_arg, args)
    cg.add(var.set_state(await cg.templatable(config["state"], args, bool)))
    return var


@automation.register_action("gp.start_queue", StartQueueAction, _target(), synchronous=True)
@automation.register_action("gp.full_cycle", FullCycleAction, _target(), synchronous=True)
@automation.register_action("gp.reset_watchdog", ResetWatchdogAction, _target(), synchronous=True)
async def simple_group_action_to_code(config, action_id, template_arg, args):
    return await _new_action(config, action_id, template_arg, args)


@automation.register_action(
    "gp.stop_all", StopAllAction, _target({cv.Optional(CONF_CLEAR_QUEUE): cv.templatable(cv.boolean)}), synchronous=True
)
async def stop_all_to_code(config, action_id, template_arg, args):
    var = await _new_action(config, action_id, template_arg, args)
    if CONF_CLEAR_QUEUE in config:
        cg.add(var.set_clear_queue(await cg.templatable(config[CONF_CLEAR_QUEUE], args, bool)))
    return var


_KEY = cv.string_strict
_ALERT_BASE = {cv.GenerateID(): cv.use_id(GpHub)}

ALERT_RAISE_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_ID): cv.use_id(GpHub),
        cv.Required(CONF_KEY): cv.templatable(cv.string),
        cv.Optional(CONF_SEVERITY, default="warn"): cv.one_of("error", "warn", "info", lower=True),
        cv.Required(CONF_TEXT): cv.templatable(cv.string),
    }
)


@automation.register_action("gp.alert_raise", AlertRaiseAction, ALERT_RAISE_SCHEMA, synchronous=True)
async def alert_raise_to_code(config, action_id, template_arg, args):
    hub = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, hub)
    cg.add(var.set_key(await cg.templatable(config[CONF_KEY], args, cg.std_string)))
    cg.add(var.set_text(await cg.templatable(config[CONF_TEXT], args, cg.std_string)))
    cg.add(var.set_severity(getattr(Severity, config[CONF_SEVERITY].upper())))
    return var


ALERT_CLEAR_SCHEMA = cv.Schema(
    {cv.Required(CONF_ID): cv.use_id(GpHub), cv.Required(CONF_KEY): cv.templatable(cv.string)}
)


@automation.register_action("gp.alert_clear", AlertClearAction, ALERT_CLEAR_SCHEMA, synchronous=True)
async def alert_clear_to_code(config, action_id, template_arg, args):
    hub = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(action_id, template_arg, hub)
    cg.add(var.set_key(await cg.templatable(config[CONF_KEY], args, cg.std_string)))
    return var


# ------------------------------------------------------------------------------------------------ conditions

_GROUP_ONLY = automation.maybe_simple_id({cv.Required(CONF_ID): cv.use_id(GpGroup)})


@automation.register_condition("gp.any_running", AnyRunningCondition, _GROUP_ONLY)
@automation.register_condition("gp.watchdog_tripped", WatchdogTrippedCondition, _GROUP_ONLY)
async def group_condition_to_code(config, condition_id, template_arg, args):
    group = await cg.get_variable(config[CONF_ID])
    return cg.new_Pvariable(condition_id, template_arg, group)


@automation.register_condition(
    "gp.zone_running",
    ZoneRunningCondition,
    cv.Schema({cv.Required(CONF_ID): cv.use_id(GpGroup), **_ZONE}),
)
async def zone_running_to_code(config, condition_id, template_arg, args):
    group = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(condition_id, template_arg, group)
    cg.add(var.set_zone(await cg.templatable(config[CONF_ZONE], args, cg.size_t)))
    return var


@automation.register_condition(
    "gp.alert_active",
    AlertActiveCondition,
    cv.Schema({cv.Required(CONF_ID): cv.use_id(GpHub), cv.Optional(CONF_KEY): cv.string}),
)
async def alert_active_to_code(config, condition_id, template_arg, args):
    hub = await cg.get_variable(config[CONF_ID])
    var = cg.new_Pvariable(condition_id, template_arg, hub)
    if CONF_KEY in config:
        cg.add(var.set_key(config[CONF_KEY]))
    return var
