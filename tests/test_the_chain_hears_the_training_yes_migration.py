"""The confidence chain hears the training yes: text pins on the migration.

Founder 2026-10-05, decisions log N48.5 Q27 A. The released rehearsal lane
proves the behaviour (tests/test_the_chain_hears_the_training_yes_postgres.py
and the chain's end-to-end suite); this file pins the TEXT: every re-issued
function differs from its latest source (manifest order) by exactly the lines
listed here and nothing else, the new functions are service-role only, and
the file is one additive transaction that opens no learning door.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
FILE = "the_chain_hears_the_training_yes.sql"
SQL = (MIGRATIONS / FILE).read_text()


def _function(sql: str, name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\(.*?\n\$\$;", sql, flags=re.S)
    assert match, name
    return match.group(0)


# (source file, the lines it loses, the lines it gains), in order.
PINS = {
    'ring_consent_is_current_v1': (
        'a_feature_reaches_a_person_by_ring.sql',
        [
            "        IF to_regproc('public.get_mlc2_principal_consent_status_v1(uuid)')",
            '           IS NULL THEN',
            "            EXECUTE 'SELECT public.get_mlc2_principal_consent_status_v1($1)'",
            "        RETURN COALESCE((answer ->> 'configured')::boolean, false)",
            "           AND COALESCE((answer ->> 'granted')::boolean, false);",
        ],
        [
            '        -- 0431 (N48.5 Q27 A): the one authority is the training yes. A',
            '        -- bundled-era grant counts for nothing (N2, N10.6). The speaker',
            '        -- binding is the half the bundled reader\'s "granted" also required:',
            '        -- the canonical promotion cannot bind a Take without it.',
            "        IF to_regprocedure('public.get_mlc2_training_consent_status_v2(uuid)')",
            '           IS NULL',
            "           OR to_regclass('public.ml_speaker_principals') IS NULL THEN",
            "            EXECUTE 'SELECT public.get_mlc2_training_consent_status_v2($1)'",
            "        IF NOT COALESCE((answer ->> 'active')::boolean, false) THEN",
            '            RETURN false;',
            '        END IF;',
            '        RETURN EXISTS (',
            '            SELECT 1 FROM public.ml_speaker_principals binding',
            '             WHERE binding.acquisition_principal_id = p_principal);',
        ],
    ),
    'ring_consent_policy_exists_v1': (
        'a_feature_reaches_a_person_by_ring.sql',
        [
            "                || 'AND (retired_at IS NULL OR retired_at > now()))'",
        ],
        [
            "                || 'AND (retired_at IS NULL OR retired_at > now()) '",
            "                || 'AND grant_scope = ''training_only'')'",
        ],
    ),
    'get_ring_confidence_readiness_v1': (
        'a_feature_reaches_a_person_by_ring.sql',
        [
            "            'consent', has_consent, 'receipts', has_receipts,",
            "            'events', has_events),",
        ],
        [
            '    eligible_training INTEGER := 0;',
            '    eligible_training_unbound INTEGER := 0;',
            '    has_training BOOLEAN := to_regprocedure(',
            "        'public.get_mlc2_training_consent_status_v2(uuid)') IS NOT NULL",
            "        AND to_regclass('public.ml_speaker_principals') IS NOT NULL;",
            '    IF has_training THEN',
            '        EXECUTE $q$',
            '            SELECT count(*) FILTER (WHERE bound),',
            '                   count(*) FILTER (WHERE NOT bound)',
            '              FROM (',
            '                SELECT EXISTS (',
            '                           SELECT 1 FROM public.ml_speaker_principals binding',
            '                            WHERE binding.acquisition_principal_id = p) AS bound',
            '                  FROM unnest($1) AS p',
            '                 WHERE COALESCE((public.get_mlc2_training_consent_status_v2(p)',
            "                                 ->> 'active')::boolean, false)",
            '              ) yes',
            '        $q$ INTO eligible_training, eligible_training_unbound USING eligible;',
            '    END IF;',
            "        'eligible_training_consent_grant_count', eligible_training,",
            "        'eligible_training_yes_without_speaker_count', eligible_training_unbound,",
            "            'consent', has_consent, 'training', has_training,",
            "            'receipts', has_receipts, 'events', has_events),",
        ],
    ),
    'get_mlc2_confidence_canary_readiness_v1': (
        'the_old_consent_code_ignores_the_training_yes.sql',
        [
        ],
        [
            '           AND length(approval.approved_copy_sha256) = 64',
            '           AND length(approval.evidence_sha256) = 64',
            "           AND NULLIF(btrim(approval.approval_reference), '') IS NOT NULL",
            "           AND NULLIF(btrim(approval.evidence_object_key), '') IS NOT NULL",
            '    ),',
            "    'active_training_consent_policy_count', (",
            '        SELECT count(*) FROM ml_consent_policies policy',
            '         WHERE policy.active_from <= now()',
            '           AND (policy.retired_at IS NULL OR policy.retired_at > now())',
            "           AND policy.grant_scope = 'training_only'",
            '    ),',
            "    'valid_active_training_consent_policy_count', (",
            '        SELECT count(*)',
            '          FROM ml_consent_policies policy',
            '          JOIN ml_product_legal_approvals approval',
            '            ON approval.id = policy.product_legal_approval_id',
            '         WHERE policy.active_from <= now()',
            '           AND (policy.retired_at IS NULL OR policy.retired_at > now())',
            '           AND NOT policy.required_for_service',
            '           AND NOT policy.bundled_ui',
            "           AND policy.grant_scope = 'training_only'",
            '           AND approval.consent_policy_version = policy.version',
            "           AND approval.article_6_basis = '6(1)(a)'",
        ],
    ),
    'promote_recording_attempt_with_mlc2_confidence_v1': (
        'the_promotion_freezes_the_consent_snapshot.sql',
        [
            '    -- now from the current bundled grant. Without a grant the snapshot RPC',
            '    -- raises and the whole promotion rolls back with it, so a Take is never',
            '    -- promoted canonically without the consent it needs.',
            '        PERFORM public.create_mlc2_consent_snapshot_v1(',
        ],
        [
            '    -- now from the current training yes (0431, N48.5 Q27 A: the bundled',
            '    -- grant admits nothing). Without a yes the snapshot RPC raises and the',
            '    -- whole promotion rolls back with it, so a Take is never promoted',
            '    -- canonically without the consent it needs.',
            '          JOIN public.ml_consent_policies policy',
            '            ON policy.version = snapshot.consent_policy_version',
            "           AND policy.grant_scope = 'training_only'",
            "           AND snapshot.retention_state = 'eligible'",
            '           AND NOT EXISTS (',
            '               SELECT 1 FROM public.ml_consent_events withdrawal',
            "                WHERE withdrawal.event_kind = 'withdraw'",
            '                  AND withdrawal.supersedes_event_id = snapshot.grant_event_id',
            '           )',
            '        PERFORM public.create_mlc2_training_consent_snapshot_v1(',
            '      JOIN public.ml_consent_policies policy',
            '        ON policy.version = snapshot.consent_policy_version',
            "       AND policy.grant_scope = 'training_only'",
        ],
    ),
}


def _diff(source: str, new: str) -> tuple[list[str], list[str]]:
    lines = list(difflib.ndiff(source.splitlines(), new.splitlines()))
    return ([line[2:] for line in lines if line.startswith("- ")],
            [line[2:] for line in lines if line.startswith("+ ")])


def _manifest() -> list[str]:
    return (MIGRATIONS / "manifest.txt").read_text().splitlines()


def test_the_manifest_lists_it_after_the_financial_records():
    names = [line.split("\t")[1] for line in _manifest() if "\t" in line]
    assert FILE in names
    assert names.index("financial_records_go_after_five_years.sql") < names.index(FILE)


def test_each_reissued_function_starts_from_its_latest_source():
    """No later file in manifest order re-issues any of them: the source
    pinned here is the definition production runs before this file."""
    names = [line.split("\t")[1] for line in _manifest() if "\t" in line]
    for function, (source, _removed, _added) in PINS.items():
        later = names[names.index(source) + 1:names.index(FILE)]
        for name in later:
            text = (MIGRATIONS / name).read_text()
            assert f"FUNCTION public.{function}(" not in text, (function, name)


def test_each_reissued_function_changes_only_the_pinned_lines():
    for function, (source, removed, added) in PINS.items():
        before = _function((MIGRATIONS / source).read_text(), function)
        after = _function(SQL, function)
        assert _diff(before, after) == (removed, added), function


def test_the_personalised_practice_door_is_left_as_0394_wrote_it():
    """0394's guard (to_regproc with an argument list) answers NULL on every
    PostgreSQL version, so that door never opens; it gates the retired
    exercise_service row, and opening it is not this decision."""
    body = _function(SQL, "ring_consent_is_current_v1")
    practice = body[body.index("'personalised_practice' THEN"):
                    body.index("ELSIF p_purpose = 'pooled_model_improvement'")]
    assert "to_regproc('public.get_phase1_consent_choices_v1(uuid)')" in practice
    pooled = body[body.index("ELSIF p_purpose = 'pooled_model_improvement'"):]
    assert "to_regprocedure('public.get_mlc2_training_consent_status_v2(uuid)')" in pooled
    assert "get_mlc2_principal_consent_status_v1" not in body


def test_the_promotion_never_calls_the_bundled_snapshot_again():
    body = _function(SQL, "promote_recording_attempt_with_mlc2_confidence_v1")
    assert "create_mlc2_consent_snapshot_v1(" not in body
    assert body.count("create_mlc2_training_consent_snapshot_v1(") == 1
    assert body.count("policy.grant_scope = 'training_only'") == 2
    assert "SET search_path = extensions, public" in body


def test_the_training_snapshot_reads_only_the_training_reader():
    body = _function(SQL, "create_mlc2_training_consent_snapshot_v1")
    assert "get_mlc2_training_consent_status_v2(" in body
    assert "policy.grant_scope = 'training_only'" in body
    assert "'personalized_coaching', jsonb_build_object(" in body
    assert "'authorized', false" in body
    assert "SET search_path = extensions, public" in body  # digest()
    for bundled in ("get_mlc2_principal_consent_status_v1", "record_mlc2_consent_grant_v1",
                    "'personalized_coaching', 'pooled_model_improvement'"):
        assert bundled not in body


def test_the_yes_is_recorded_before_the_speaker_is_bound():
    body = _function(SQL, "accept_mlc2_training_consent_v1")
    assert body.index("record_mlc2_training_consent_grant_v2(") <         body.index("bind_mlc2_training_speaker_v1(")
    bind = _function(SQL, "bind_mlc2_training_speaker_v1")
    assert bind.index("WHERE acquisition_principal_id = p_acquisition_principal_id") <         bind.index("get_mlc2_training_consent_status_v2(")
    assert bind.index("get_mlc2_training_consent_status_v2(") <         bind.index("register_ml_speaker_principal_v1(")
    assert "'verified_account_link'" in bind


def test_the_blind_rating_reader_is_blind_coach_only():
    body = _function(SQL, "get_mlc2_blind_coach_ratings_v1")
    assert "judgment.actor_provenance = 'blind_coach'" in body
    assert "packet.reviewer_role = 'coach'" in body
    for other in ("user_self_report", "blind_peer", "professional_evaluation",
                  "confidence_labels", "ml_machine_predictions"):
        assert other not in body


NEW_FUNCTIONS = (
    "create_mlc2_training_consent_snapshot_v1",
    "bind_mlc2_training_speaker_v1",
    "accept_mlc2_training_consent_v1",
    "get_mlc2_blind_coach_ratings_v1",
    # F-3
    "get_mlc2_speaker_splits_v1",
    # F-8
    "record_mlc2_object_verification_v1",
    "list_mlc2_objects_due_verification_v1",
    "record_pair_release_verification_v1",
)


def test_every_function_here_is_service_role_only():
    created = re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)\(", SQL)
    assert set(created) == set(PINS) | set(NEW_FUNCTIONS)
    for function in created:
        assert re.search(rf"REVOKE ALL ON FUNCTION public\.{function}\(.*?FROM PUBLIC, "
                         rf"anon, authenticated;", SQL, flags=re.S), function
        assert re.search(rf"GRANT EXECUTE ON FUNCTION public\.{function}\(.*?TO "
                         rf"service_role;", SQL, flags=re.S), function


#: The one table this migration creates (F-8) and the one ALTER it needs.
NEW_TABLE_LINES = (
    "create table if not exists public.pair_release_verifications (",
    "alter table public.pair_release_verifications enable row level security;",
)


def test_one_additive_transaction_that_opens_no_door():
    code = "\n".join(line.split("--", 1)[0] for line in SQL.splitlines()).lower()
    assert code.count("begin;") == 1 and code.count("commit;") == 1
    for line in NEW_TABLE_LINES:
        assert code.count(line) == 1, line
        code = code.replace(line, "")
    for forbidden in ("drop ", "truncate", "delete from", "alter table",
                      "insert into public.feature_rings", "update public.",
                      "current_setting(", "founder_canary", "create table"):
        assert forbidden not in code, forbidden


# ── F-8: verifications ───────────────────────────────────────────────────

def test_the_object_writer_decides_verified_itself_and_only_appends():
    body = _function(SQL, "record_mlc2_object_verification_v1")
    signature = body.split(") RETURNS", 1)[0]
    assert "p_verified" not in signature  # no caller can declare an object verified
    assert "v_verified := p_observed_sha256 = lower(v_object.sha256)" in body
    assert "AND p_observed_byte_size = v_object.byte_size" in body
    assert "INSERT INTO public.ml_object_verifications" in body
    assert "RETURN NULL" in body  # a key that is no chain object writes nothing
    for verb in ("UPDATE ", "DELETE ", "INSERT INTO public.ml_object_artifacts"):
        assert verb not in body, verb


def test_the_work_list_hands_out_coordinates_not_hashes():
    body = _function(SQL, "list_mlc2_objects_due_verification_v1")
    returns = body.split("AS $$", 1)[0]
    assert "sha256" not in returns and "byte_size" not in returns
    assert "NULLS FIRST" in body and "LIMIT LEAST(" in body
    assert "source.deleted_at IS NOT NULL" in body


def test_the_release_ledger_is_append_only_and_server_only():
    assert "REFERENCES public.pair_releases(id) ON DELETE RESTRICT" in SQL
    assert ("REVOKE ALL ON TABLE public.pair_release_verifications\n"
            "    FROM PUBLIC, anon, authenticated, service_role;") in SQL
    assert ("GRANT SELECT ON TABLE public.pair_release_verifications "
            "TO service_role;") in SQL
    assert ("BEFORE UPDATE OR DELETE ON public.pair_release_verifications\n"
            "            FOR EACH ROW EXECUTE FUNCTION "
            "public.reject_mlc2_immutable_mutation();") in SQL
    # The trigger is created only when absent: reapplying never drops it.
    assert "tgname = 'pair_release_verifications_append_only'" in SQL


def test_the_release_writer_compares_with_the_release_row():
    body = _function(SQL, "record_pair_release_verification_v1")
    signature = body.split(") RETURNS", 1)[0]
    assert "p_verified" not in signature
    assert "WHEN 'file' THEN p_observed_sha256 = v_release.file_sha256" in body
    assert "ELSE p_observed_sha256 = v_release.manifest_sha256" in body
    assert "AND p_signature_valid" in body
    assert "INSERT INTO public.pair_release_verifications" in body
    for verb in ("UPDATE ", "DELETE "):
        assert verb not in body, verb


def test_the_released_lane_applies_it_twice():
    recipe = (ROOT / "tests" / "integration" / "confident_moment_rehearsal.sh").read_text()
    assert recipe.count(f"hard migrations/{FILE}") == 2
    tier = (ROOT / "scripts" / "rehearsal_tier.sh").read_text()
    assert "tests/test_the_chain_hears_the_training_yes_postgres.py" in tier


def test_the_split_reader_reads_the_binding_and_the_assignment_only():
    body = _function(SQL, "get_mlc2_speaker_splits_v1")
    assert "JOIN public.ml_speaker_split_assignments assignment" in body
    assert "assignment.split_policy_version = p_split_policy_version" in body
    for verb in ("INSERT ", "UPDATE ", "DELETE "):
        assert verb not in body, verb

