#!/usr/bin/env python3
"""
Migration 008 Seed Data: Surveillance Configuration & Test Types.

Populates surveillance_config with system defaults and surveillance_test_config
with standard test types (DGA, BDV, IR, Oil Quality) for Power Transformer equipment.

Loads surveillance workflow and stage definitions from JSON files following
the same pattern as REPAIR, CALIBRATION, and OVERHAUL workflows.

References CategoryMaster and CategoryDetails for equipment/test type IDs to
maintain single source of truth.

Run after migration 008:
    python run_migration_008_seed.py
"""
import sys
import json
import os
from database import VendorSessionLocal
from sqlalchemy import text


def run_seed():
    print("=" * 70)
    print("  Migration 008 Seed: Surveillance Configuration")
    print("=" * 70)

    session = VendorSessionLocal()
    try:
        # ───────────────────────────────────────────────────────────────────
        # 1. Insert system-wide default surveillance configuration
        # ───────────────────────────────────────────────────────────────────
        print("\n[1/3] Creating system-wide surveillance config...")

        session.execute(text("""
            INSERT INTO public.surveillance_config (
                organization_id,
                department_id,
                surveillance_period_months,
                frequency_multiplier,
                abnormal_statuses,
                quality_threshold_fair,
                is_active
            )
            VALUES (
                NULL,  -- system-wide default
                NULL,
                24,    -- 24-month surveillance period
                2.0,   -- 2x frequency (normal 12mo → surveillance 6mo)
                '["FAIL", "MARGINAL", "CRITICAL", "ALERT"]'::jsonb,
                20.0,  -- ≥20% abnormal = POOR quality rating
                true
            )
            ON CONFLICT DO NOTHING
        """))
        session.commit()
        print("  [OK] System default config created")

        # ───────────────────────────────────────────────────────────────────
        # 2. Get equipment type ID for Power Transformer
        # ───────────────────────────────────────────────────────────────────
        print("\n[2/3] Resolving equipment type: Power Transformer...")

        result = session.execute(text("""
            SELECT id, name
            FROM public."CategoryMaster"
            WHERE category = 'equipment'
              AND name ILIKE '%power%transformer%'
            LIMIT 1
        """))
        equipment_row = result.fetchone()

        if not equipment_row:
            print("  [WARN] Power Transformer equipment type not found in CategoryMaster")
            print("  [INFO] Skipping surveillance_test_config seed (run manually after equipment types are configured)")
            session.close()
            return

        equipment_id = equipment_row[0]
        equipment_name = equipment_row[1]
        print(f"  [OK] Found: {equipment_name} (ID: {equipment_id})")

        # ───────────────────────────────────────────────────────────────────
        # 3. Get test type IDs and insert surveillance test config
        # ───────────────────────────────────────────────────────────────────
        print("\n[3/3] Creating surveillance test configurations...")

        # Standard surveillance test types
        test_types = [
            ("DGA", "high", 180),           # Dissolved Gas Analysis - every 6 months
            ("BDV", "high", 180),           # Breakdown Voltage - every 6 months
            ("IR", "high", 180),            # Insulation Resistance - every 6 months
            ("Oil Quality", "high", 180),   # Oil Quality Check - every 6 months
        ]

        inserted_count = 0
        for test_name, priority, periodicity in test_types:
            # Query CategoryDetails for test type
            result = session.execute(text("""
                SELECT id, name
                FROM public."CategoryDetails"
                WHERE category = 'test'
                  AND name ILIKE :test_name
                LIMIT 1
            """), {"test_name": f"%{test_name}%"})
            test_row = result.fetchone()

            if not test_row:
                print(f"  [WARN] Test type '{test_name}' not found in CategoryDetails - skipping")
                continue

            test_id = test_row[0]
            test_full_name = test_row[1]

            # Insert surveillance test config
            session.execute(text("""
                INSERT INTO public.surveillance_test_config (
                    equipment_type_id,
                    test_type_id,
                    is_required,
                    default_priority,
                    custom_periodicity_days,
                    is_active
                )
                VALUES (
                    :equipment_id,
                    :test_id,
                    true,
                    :priority,
                    :periodicity,
                    true
                )
                ON CONFLICT (equipment_type_id, test_type_id) DO NOTHING
            """), {
                "equipment_id": equipment_id,
                "test_id": test_id,
                "priority": priority,
                "periodicity": periodicity
            })
            session.commit()
            print(f"  [OK] {test_full_name} → {periodicity} days, priority: {priority}")
            inserted_count += 1

        # ───────────────────────────────────────────────────────────────────
        # 4. Create surveillance workflow definition + stage definitions
        # ───────────────────────────────────────────────────────────────────
        print("\n[4/5] Creating surveillance workflow definition...")

        # Check if surveillance workflow definition already exists
        result = session.execute(text("""
            SELECT id FROM repair_workflow_definitions
            WHERE workflow_code = 'SURVEILLANCE'
        """))
        existing_def = result.fetchone()

        if existing_def:
            print(f"  [OK] Surveillance workflow definition already exists (id: {existing_def[0]})")
            workflow_def_id = existing_def[0]
        else:
            # Create surveillance workflow definition
            session.execute(text("""
                INSERT INTO repair_workflow_definitions (
                    id, workflow_code, workflow_name, description, is_active
                )
                VALUES (
                    gen_random_uuid(),
                    'SURVEILLANCE',
                    'Post-Commissioning Surveillance',
                    '24-month surveillance workflow with quarterly testing and final evaluation',
                    true
                )
                RETURNING id
            """))
            result = session.execute(text("""
                SELECT id FROM repair_workflow_definitions
                WHERE workflow_code = 'SURVEILLANCE'
            """))
            workflow_def_id = result.fetchone()[0]
            session.commit()
            print(f"  [OK] Created surveillance workflow definition (id: {workflow_def_id})")

        # ───────────────────────────────────────────────────────────────────
        # 5. Load stage definitions from JSON and create stages
        # ───────────────────────────────────────────────────────────────────
        print("\n[5/6] Loading stage definitions from JSON...")

        # Load SURVEILLANCE_WORKFLOW_STAGES.json
        stages_json_path = os.path.join(os.path.dirname(__file__), 'SURVEILLANCE_WORKFLOW_STAGES.json')
        if not os.path.exists(stages_json_path):
            print(f"  [ERROR] JSON file not found: {stages_json_path}")
            sys.exit(1)

        with open(stages_json_path, 'r') as f:
            workflow_stages = json.load(f)

        # Load SURVEILLANCE_STAGE_TEMPLATE_MAP.json
        template_map_path = os.path.join(os.path.dirname(__file__), 'SURVEILLANCE_STAGE_TEMPLATE_MAP.json')
        if not os.path.exists(template_map_path):
            print(f"  [ERROR] JSON file not found: {template_map_path}")
            sys.exit(1)

        with open(template_map_path, 'r') as f:
            template_map = json.load(f)

        print(f"  [OK] Loaded {len(workflow_stages)} stage definitions from JSON")

        # Create stage definitions
        stages_created = 0
        for stage_data in workflow_stages:
            stage_name = stage_data['name']
            stage_sequence = stage_data['sequence']

            # Derive stage code from name
            # "Q1 Surveillance Testing" → "Q1_SURVEILLANCE"
            # "Final Evaluation & Report" → "FINAL_EVALUATION"
            if stage_name.startswith('Q'):
                quarter_num = stage_name[1]  # Extract '1', '2', '3', or '4'
                stage_code = f'Q{quarter_num}_SURVEILLANCE'
            else:
                stage_code = 'FINAL_EVALUATION'

            # Get template key from map
            template_key = template_map.get(stage_name, 'surveillance_quarter_review')

            # Prepare stage config
            stage_config = {
                'code': stage_code,
                'name': stage_name,
                'description': f'{stage_name} stage',
                'stage_number': stage_sequence,
                'template_key': template_key,
            }

            # Check if stage already exists
            # Check if stage already exists
            result = session.execute(text("""
                SELECT id FROM repair_stage_definitions
                WHERE workflow_definition_id = :workflow_def_id
                  AND code = :code
            """), {"workflow_def_id": workflow_def_id, "code": stage_config['code']})
            existing_stage = result.fetchone()

            if existing_stage:
                print(f"  [OK] Stage '{stage_config['name']}' already exists")
                continue

            # Create stage definition
            session.execute(text("""
                INSERT INTO repair_stage_definitions (
                    id,
                    workflow_definition_id,
                    code,
                    name,
                    description,
                    stage_number,
                    template_key,
                    requires_approval,
                    is_active
                )
                VALUES (
                    gen_random_uuid(),
                    :workflow_def_id,
                    :code,
                    :name,
                    :description,
                    :stage_number,
                    :template_key,
                    true,
                    true
                )
            """), {
                "workflow_def_id": workflow_def_id,
                "code": stage_config['code'],
                "name": stage_config['name'],
                "description": stage_config['description'],
                "stage_number": stage_config['stage_number'],
                "template_key": stage_config['template_key'],
            })
            stages_created += 1
            print(f"  [OK] Created stage: {stage_config['name']}")

        session.commit()

        # ───────────────────────────────────────────────────────────────────
        # 6. Create stage transitions (Q1→Q2→Q3→Q4→Final)
        # ───────────────────────────────────────────────────────────────────
        print("\n[6/6] Creating stage transitions...")

        # Get stage IDs
        result = session.execute(text("""
            SELECT id, code FROM repair_stage_definitions
            WHERE workflow_definition_id = :workflow_def_id
            ORDER BY stage_number
        """), {"workflow_def_id": workflow_def_id})
        stages = result.fetchall()
        stage_map = {code: stage_id for stage_id, code in stages}

        transitions = [
            ('Q1_SURVEILLANCE', 'Q2_SURVEILLANCE', 'approve'),
            ('Q2_SURVEILLANCE', 'Q3_SURVEILLANCE', 'approve'),
            ('Q3_SURVEILLANCE', 'Q4_SURVEILLANCE', 'approve'),
            ('Q4_SURVEILLANCE', 'FINAL_EVALUATION', 'approve'),
        ]

        transitions_created = 0
        for from_code, to_code, action in transitions:
            from_stage_id = stage_map.get(from_code)
            to_stage_id = stage_map.get(to_code)

            if not from_stage_id or not to_stage_id:
                print(f"  [WARN] Cannot create transition {from_code}→{to_code} (stages not found)")
                continue

            # Check if transition already exists
            result = session.execute(text("""
                SELECT id FROM repair_stage_transitions
                WHERE from_stage_id = :from_id AND to_stage_id = :to_id AND action = :action
            """), {"from_id": from_stage_id, "to_id": to_stage_id, "action": action})
            existing_transition = result.fetchone()

            if existing_transition:
                continue

            # Create transition
            session.execute(text("""
                INSERT INTO repair_stage_transitions (
                    id, from_stage_id, to_stage_id, action, label
                )
                VALUES (
                    gen_random_uuid(),
                    :from_id,
                    :to_id,
                    :action,
                    :label
                )
            """), {
                "from_id": from_stage_id,
                "to_id": to_stage_id,
                "action": action,
                "label": f"Complete {from_code.replace('_', ' ').title()}"
            })
            transitions_created += 1

        session.commit()
        print(f"  [OK] Created {transitions_created} stage transitions")

        # ───────────────────────────────────────────────────────────────────
        # 7. Load and create stage role permissions from JSON
        # ───────────────────────────────────────────────────────────────────
        print("\n[7/7] Creating stage role permissions...")

        # Load SURVEILLANCE_STAGE_ROLES.json
        roles_json_path = os.path.join(os.path.dirname(__file__), 'SURVEILLANCE_STAGE_ROLES.json')
        if not os.path.exists(roles_json_path):
            print(f"  [WARN] Role config not found: {roles_json_path} - skipping role setup")
        else:
            with open(roles_json_path, 'r') as f:
                stage_roles_config = json.load(f)

            roles_created = 0
            for role_config in stage_roles_config:
                stage_code = role_config['stage_code']
                roles = role_config.get('roles', [])

                # Get stage_id from stage_code
                result = session.execute(text("""
                    SELECT id FROM repair_stage_definitions
                    WHERE workflow_definition_id = :workflow_def_id
                      AND code = :stage_code
                """), {"workflow_def_id": workflow_def_id, "stage_code": stage_code})
                stage_row = result.fetchone()

                if not stage_row:
                    print(f"  [WARN] Stage {stage_code} not found - skipping role setup")
                    continue

                stage_id = stage_row[0]

                # Create role permissions for each role
                for role_name in roles:
                    # Get or find role_id from org_roles table
                    result = session.execute(text("""
                        SELECT id FROM org_roles
                        WHERE role_name = :role_name
                        LIMIT 1
                    """), {"role_name": role_name})
                    role_row = result.fetchone()

                    if not role_row:
                        print(f"  [WARN] Role '{role_name}' not found in org_roles - skipping")
                        continue

                    role_id = role_row[0]

                    # Check if role permission already exists
                    result = session.execute(text("""
                        SELECT id FROM repair_stage_roles
                        WHERE stage_id = :stage_id AND role_id = :role_id
                    """), {"stage_id": stage_id, "role_id": role_id})
                    existing_role = result.fetchone()

                    if existing_role:
                        continue

                    # Create role permission
                    session.execute(text("""
                        INSERT INTO repair_stage_roles (
                            id, stage_id, role_id, can_edit, can_approve
                        )
                        VALUES (
                            gen_random_uuid(),
                            :stage_id,
                            :role_id,
                            true,
                            true
                        )
                    """), {"stage_id": stage_id, "role_id": role_id})
                    roles_created += 1

            session.commit()
            print(f"  [OK] Created {roles_created} role permissions")

        # ───────────────────────────────────────────────────────────────────
        # Verification Summary
        # ───────────────────────────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("  [SUCCESS] Surveillance seed data complete")
        print("\n  Summary:")
        print("  • System-wide config: 24-month surveillance, 2x frequency")
        print(f"  • Test configurations: {inserted_count} inserted")
        print(f"  • Workflow definition: SURVEILLANCE")
        print(f"  • Stage definitions: {stages_created} created (5 total)")
        print(f"  • Stage transitions: {transitions_created} created")
        print("\n  Next steps:")
        print("  1. Review surveillance_config table")
        print("  2. Review surveillance_test_config table")
        print("  3. Review repair_workflow_definitions (SURVEILLANCE)")
        print("  4. Test surveillance workflow creation on repair completion")
        print("=" * 70 + "\n")

    except Exception as exc:
        print(f"\n[FAILED] {exc}")
        import traceback
        traceback.print_exc()
        session.rollback()
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    run_seed()
