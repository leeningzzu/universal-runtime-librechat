from enum import StrEnum


class PersistenceClass(StrEnum):
    EPHEMERAL = 'EPHEMERAL'
    CACHE = 'CACHE'
    WORKING = 'WORKING'
    AUDIT = 'AUDIT'
    AUTHORITATIVE = 'AUTHORITATIVE'


class GateVerdict(StrEnum):
    PASS = 'PASS'
    REVISE = 'REVISE'
    HISTORY_BOUNDARY_BLOCKER = 'HISTORY_BOUNDARY_BLOCKER'
