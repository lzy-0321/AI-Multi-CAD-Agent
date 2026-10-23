"""Allowlisted, shareable diagnosis: never include raw errors, arguments or env."""
import time
from pathlib import Path
from .project import write_json


def report(status):
    result = {'schema_version': 1, 'generated_at': time.time(), 'backends': {},
              'privacy': 'No command arguments, environment values, raw errors or model content included'}
    for name in ('blender', 'solidworks'):
        source = status.get(name, {})
        item = {key: source.get(key, 'not_checked') for key in (
            'installed', 'registered', 'registration_matches', 'mcp_configured',
            'mcp_connected', 'cad_callable', 'uncertain_write', 'tool_count')}
        verification = source.get('verification_history') or source.get('capabilities_verified')
        if isinstance(verification, dict):
            known = {'parametric_plate', 'reopen', 'geometry_validation', 'parameter_mapping', 'edit_diameter'}
            item['business_verification'] = {
                'historical': True, 'verified_at': verification.get('verified_at'),
                'config_matches': verification.get('config_matches', True),
                'capabilities': [v for v in verification.get('capabilities', []) if v in known]}
        else:
            item['business_verification'] = {'status': 'not_verified'}
        actions = []
        if not source.get('installed') or not source.get('mcp_configured'):
            actions.append('Run setup --repair to configure software and MCP paths')
        if source.get('registration_matches') is False:
            actions.append('Select the COM-registered SolidWorks installation or repair its registration')
        if source.get('mcp_connected') is False:
            actions.append('Check local MCP command, dependencies and stderr log; run doctor --live again')
        if source.get('cad_callable') is False:
            actions.append('Open CAD and check license; for Blender enable the addon on the selected version and loopback port')
        if source.get('uncertain_write'):
            actions.append('Inspect actual CAD state before reconcile_write; do not replay the write')
        item['next_actions'] = actions
        result['backends'][name] = item
    return result


def save_report(path, status):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = report(status)
    write_json(path, value)
    return value
