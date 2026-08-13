"""
Test Result Templates — Template-driven dynamic forms for each test type.

Each template defines sections and fields that the Flutter UI renders dynamically.
Test results are stored as JSONB in a single test_results table.

Field types: text, number, dropdown, boolean, textarea, table, date, checkbox
  - checkbox : single tick-box (checklist item), value stored as true/false string
               Use for checklists (maintenance, inspection). Different from 'boolean'
               (toggle switch) — checkbox renders as a compact tick with label.
  - boolean  : toggle/switch for yes-no answers with prominence
  - checkbox_group : NOT YET SUPPORTED (use multiple checkbox fields instead)

Multi-session support:
- supports_multi_session: Boolean indicating if this test type can have multiple sessions
- typical_session_interval_days: Typical number of days between sessions
- typical_total_sessions: Typical number of sessions for this test type
"""

# ─── Shared evaluation severity maps (referenced by field/column definitions) ────
# Template-driven: the code reads these from column_evaluation / dropdown_evaluation.
# No test-type knowledge in evaluation_service.py — severity comes entirely from here.

_EV_PF     = {"Pass": "NORMAL", "Fail": "CRITICAL"}
_EV_PFNA   = {"Pass": "NORMAL", "Fail": "CRITICAL", "N/A": "NORMAL"}
_EV_PFNT   = {"Pass": "NORMAL", "Fail": "CRITICAL", "Not Tested": "NORMAL"}
_EV_PFCR   = {"Pass": "NORMAL", "Fail": "CRITICAL", "Conditional": "ALERT", "Retest": "ALERT"}
_EV_PFC    = {"Pass": "NORMAL", "Fail": "CRITICAL", "Conditional": "ALERT"}
_EV_PFM    = {"Pass": "NORMAL", "Fail": "CRITICAL", "Monitor": "ALERT", "Marginal": "ALERT"}
_EV_PFTP   = {"Pass": "NORMAL", "Fail": "CRITICAL", "Topped Up - Pass": "NORMAL"}
_EV_PFGR   = {"Pass": "NORMAL", "Fail": "CRITICAL", "Gas Replaced - Pass": "NORMAL"}
_EV_PAF    = {"PASS": "NORMAL", "ALERT": "ALERT", "FAIL": "CRITICAL"}
_EV_PCF    = {"PASS": "NORMAL", "CONDITIONAL": "ALERT", "FAIL": "CRITICAL"}
_EV_NAC    = {
    "Normal": "NORMAL", "Alert": "ALERT",
    "Critical": "CRITICAL", "Critical / Abnormal": "CRITICAL", "Abnormal": "CRITICAL",
}
_EV_NHC    = {"Normal": "NORMAL", "High": "ALERT", "Low": "ALERT",
              "Critical": "CRITICAL", "Critical Low": "CRITICAL"}
_EV_GFP    = {"Good": "NORMAL", "Fair": "ALERT", "Poor": "CRITICAL", "Damaged": "CRITICAL"}
_EV_SAT    = {
    "Satisfactory": "NORMAL",
    "Satisfactory with Observations": "ALERT",
    "Unsatisfactory": "CRITICAL",
    "Unsatisfactory — Rework Required": "CRITICAL",
    "Action Required": "CRITICAL",
}
_EV_TRIP   = {"Trip": "NORMAL", "No Trip": "CRITICAL",
              "Stable (No Trip)": "NORMAL", "Unstable (Tripped)": "CRITICAL"}
_EV_COMPLY = {"Compliant": "NORMAL", "Partial": "ALERT", "Non-Compliant": "CRITICAL"}
_EV_SFRA_ASSESS = {
    "Normal": "NORMAL", "Slight Deviation": "ALERT",
    "Marginal": "ALERT", "Abnormal": "CRITICAL",
}
_EV_MOISTURE = {
    "As new": "NORMAL", "Dry": "NORMAL",
    "Moderately Wet": "ALERT", "Wet": "CRITICAL", "Very Wet": "CRITICAL",
}
_EV_OIL_COND = {
    "As new": "NORMAL", "Acceptable": "NORMAL", "Poor": "ALERT", "Bad": "CRITICAL",
}


TEST_TEMPLATES = {
    # ────────────────────────────────────────────────────────────
    # 1. Relay Testing Report (Feeder protection relays)
    # ────────────────────────────────────────────────────────────
    "relay_testing_report": {
        "key": "relay_testing_report",
        "name": "Relay Testing Report",
        "equipment_type": "Feeder protection relays",
        "description": "Complete relay testing report with overcurrent and earth fault tests",
        "supports_multi_session": False,  # Single session test
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "sections": [
            {
                "title": "Relay Information",
                "fields": [
                    {"key": "relay_make", "label": "Relay Make", "type": "text", "required": True},
                    {"key": "relay_model", "label": "Relay Model/Type", "type": "text", "required": True},
                    {"key": "relay_serial", "label": "Relay Serial Number", "type": "text", "required": True},
                    {"key": "ct_ratio", "label": "CT Ratio", "type": "text", "required": True, "placeholder": "e.g. 200/1"},
                    {"key": "rated_current", "label": "Rated Current", "type": "number", "unit": "A", "required": True},
                    {"key": "rated_voltage", "label": "Rated Voltage", "type": "number", "unit": "kV", "required": True},
                ]
            },
            {
                "title": "Overcurrent Test (Phase)",
                "fields": [
                    {"key": "oc_phase_pickup", "label": "Pickup Current (Set)", "type": "number", "unit": "A", "required": True},
                    {"key": "oc_phase_pickup_actual", "label": "Pickup Current (Actual)", "type": "number", "unit": "A", "required": True},
                    {"key": "oc_phase_tms", "label": "TMS Setting", "type": "number", "required": True},
                    {"key": "oc_phase_curve", "label": "Curve Type", "type": "dropdown", "options": ["Normal Inverse", "Very Inverse", "Extremely Inverse", "Definite Time"], "required": True},
                    {"key": "oc_phase_operating_time", "label": "Operating Time at 2x", "type": "number", "unit": "sec"},
                    {"key": "oc_phase_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PF}},
                ]
            },
            {
                "title": "Earth Fault Test",
                "fields": [
                    {"key": "ef_pickup", "label": "EF Pickup Current (Set)", "type": "number", "unit": "A", "required": True},
                    {"key": "ef_pickup_actual", "label": "EF Pickup Current (Actual)", "type": "number", "unit": "A", "required": True},
                    {"key": "ef_tms", "label": "EF TMS Setting", "type": "number"},
                    {"key": "ef_operating_time", "label": "EF Operating Time", "type": "number", "unit": "sec"},
                    {"key": "ef_result", "label": "EF Test Result", "type": "dropdown", "options": ["Pass", "Fail"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PF}},
                ]
            },
            {
                "title": "Trip Circuit Test",
                "fields": [
                    {"key": "trip_circuit_ok", "label": "Trip Circuit Healthy", "type": "boolean", "required": True},
                    {"key": "trip_coil_resistance", "label": "Trip Coil Resistance", "type": "number", "unit": "ohms"},
                    {"key": "trip_time", "label": "Trip Time", "type": "number", "unit": "ms"},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks / Observations", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 2. Differential Protection Test (Power transformers)
    # ────────────────────────────────────────────────────────────
    "differential_protection_test": {
        "key": "differential_protection_test",
        "name": "Differential Protection Test",
        "equipment_type": "Power transformers",
        "description": "Differential protection relay testing with stability verification",
        "sections": [
            {
                "title": "Relay Information",
                "fields": [
                    {"key": "relay_make", "label": "Relay Make", "type": "text", "required": True},
                    {"key": "relay_model", "label": "Relay Model", "type": "text", "required": True},
                    {"key": "relay_serial", "label": "Serial Number", "type": "text"},
                    {"key": "ct_ratio_hv", "label": "CT Ratio (HV Side)", "type": "text", "required": True},
                    {"key": "ct_ratio_lv", "label": "CT Ratio (LV Side)", "type": "text", "required": True},
                ]
            },
            {
                "title": "Differential Settings",
                "fields": [
                    {"key": "diff_pickup", "label": "Differential Pickup", "type": "number", "unit": "A", "required": True},
                    {"key": "slope_1", "label": "Slope 1", "type": "number", "unit": "%", "required": True},
                    {"key": "slope_2", "label": "Slope 2", "type": "number", "unit": "%"},
                    {"key": "second_harmonic_block", "label": "2nd Harmonic Block", "type": "number", "unit": "%"},
                    {"key": "fifth_harmonic_block", "label": "5th Harmonic Block", "type": "number", "unit": "%"},
                ]
            },
            {
                "title": "Test Results",
                "fields": [
                    {
                        "key": "diff_test_readings",
                        "label": "Differential Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "test_condition", "label": "Test Condition", "type": "text"},
                            {"key": "hv_current", "label": "HV Current (A)", "type": "number"},
                            {"key": "lv_current", "label": "LV Current (A)", "type": "number"},
                            {"key": "diff_current", "label": "Diff Current (A)", "type": "number"},
                            {"key": "relay_operation", "label": "Relay Op.", "type": "dropdown", "options": ["Trip", "No Trip"], "column_evaluation": _EV_TRIP},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Stability Test",
                "fields": [
                    {"key": "through_fault_current", "label": "Through Fault Current", "type": "number", "unit": "A"},
                    {"key": "stability_result", "label": "Stability Test Result", "type": "dropdown", "options": ["Stable (No Trip)", "Unstable (Tripped)"], "required": True},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 3. Stability / Bias Test (Transformer differential relay)
    # ────────────────────────────────────────────────────────────
    "stability_bias_test": {
        "key": "stability_bias_test",
        "name": "Stability / Bias Test",
        "equipment_type": "Transformer differential relay",
        "description": "Stability and bias characteristic verification of differential relay",
        "sections": [
            {
                "title": "Relay Details",
                "fields": [
                    {"key": "relay_make", "label": "Relay Make", "type": "text", "required": True},
                    {"key": "relay_model", "label": "Relay Model", "type": "text", "required": True},
                    {"key": "relay_serial", "label": "Serial Number", "type": "text"},
                    {"key": "rated_current", "label": "Rated Current", "type": "number", "unit": "A", "required": True},
                ]
            },
            {
                "title": "Bias Characteristic Test",
                "fields": [
                    {
                        "key": "bias_readings",
                        "label": "Bias Characteristic Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "bias_current", "label": "Bias Current (A)", "type": "number"},
                            {"key": "diff_current_pickup", "label": "Diff Pickup (A)", "type": "number"},
                            {"key": "expected_pickup", "label": "Expected Pickup (A)", "type": "number"},
                            {"key": "deviation", "label": "Deviation (%)", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Stability Verification",
                "fields": [
                    {"key": "max_through_fault", "label": "Max Through Fault Current", "type": "number", "unit": "A"},
                    {"key": "relay_stable", "label": "Relay Stable (No Maloperation)", "type": "boolean", "required": True},
                    {"key": "stability_margin", "label": "Stability Margin", "type": "number", "unit": "%"},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 4. Protection Relay Functional Test (Protection relays)
    # ────────────────────────────────────────────────────────────
    "protection_relay_functional_test": {
        "key": "protection_relay_functional_test",
        "name": "Protection Relay Functional Test",
        "equipment_type": "Protection Relay",
        "description": "Functional verification of protection relay settings and operation",
        "sections": [
            {
                "title": "Relay Information",
                "fields": [
                    {"key": "relay_make", "label": "Relay Make", "type": "text", "required": True},
                    {"key": "relay_type", "label": "Relay Type", "type": "text", "required": True},
                    {"key": "relay_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "protection_function", "label": "Protection Function", "type": "dropdown", "options": ["Overcurrent", "Earth Fault", "Distance", "Differential", "Under Voltage", "Over Voltage"], "required": True},
                ]
            },
            {
                "title": "Setting Verification",
                "fields": [
                    {
                        "key": "setting_readings",
                        "label": "Setting Verification",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "parameter", "label": "Parameter", "type": "text"},
                            {"key": "set_value", "label": "Set Value", "type": "text"},
                            {"key": "measured_value", "label": "Measured Value", "type": "text"},
                            {"key": "tolerance", "label": "Tolerance (%)", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Functional Tests",
                "fields": [
                    {"key": "trip_test_ok", "label": "Trip Test Successful", "type": "boolean", "required": True},
                    {"key": "close_test_ok", "label": "Close Test Successful", "type": "boolean"},
                    {"key": "flag_indication_ok", "label": "Flag/LED Indication OK", "type": "boolean", "required": True},
                    {"key": "alarm_contacts_ok", "label": "Alarm Contacts OK", "type": "boolean"},
                    {"key": "auxiliary_supply", "label": "Auxiliary Supply", "type": "number", "unit": "V DC"},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 5. Insulation Resistance (IR) Test (Current transformers / Transformer)
    # ────────────────────────────────────────────────────────────
    "insulation_resistance_test": {
        "key": "insulation_resistance_test",
        "name": "Insulation Resistance (IR) Test",
        "equipment_type": "Current Transformer",
        "description": "Insulation resistance measurement using megger",
        "sections": [
            {
                "title": "Equipment Information",
                "fields": [
                    {"key": "equipment_make", "label": "Equipment Make", "type": "text", "required": True},
                    {"key": "equipment_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "megger_make", "label": "Megger Make/Model", "type": "text", "required": True},
                    {"key": "test_voltage", "label": "Test Voltage", "type": "dropdown", "options": ["500V", "1000V", "2500V", "5000V"], "required": True},
                    {"key": "temperature", "label": "Ambient Temperature", "type": "number", "unit": "deg C"},
                    {"key": "humidity", "label": "Humidity", "type": "number", "unit": "%"},
                ]
            },
            {
                "title": "IR Measurements",
                "fields": [
                    {
                        "key": "ir_readings",
                        "label": "IR Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "winding", "label": "Winding/Phase", "type": "text"},
                            {"key": "measurement_point", "label": "Measurement", "type": "text"},
                            {"key": "ir_value_1min", "label": "IR 1min (MOhm)", "type": "number"},
                            {"key": "ir_value_10min", "label": "IR 10min (MOhm)", "type": "number"},
                            {
                                "key": "pi_value",
                                "label": "PI (Polarisation Index)",
                                "type": "calculated",
                                "formula": "ratio(ir_value_10min, ir_value_1min)"
                            },
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ],
                        "column_summaries": {
                            "ir_value_1min": "avg",
                            "ir_value_10min": "avg",
                            "pi_value": "avg"
                        }
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "min_acceptable_ir", "label": "Min Acceptable IR", "type": "number", "unit": "MOhm"},
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 6. CT Ratio Test (Current transformers)
    # ────────────────────────────────────────────────────────────
    "ct_ratio_test": {
        "key": "ct_ratio_test",
        "name": "CT Ratio Test",
        "equipment_type": "Current Transformer",
        "description": "Current transformer ratio and polarity verification",
        "sections": [
            {
                "title": "CT Identification",
                "fields": [
                    {"key": "ct_make", "label": "CT Make", "type": "text", "required": True},
                    {"key": "ct_serial", "label": "CT Serial Number", "type": "text", "required": True},
                    {"key": "ct_class", "label": "CT Class", "type": "text", "placeholder": "e.g. 0.5, 5P20"},
                    {"key": "rated_ratio", "label": "Rated CT Ratio", "type": "text", "required": True, "placeholder": "e.g. 200/5"},
                    {"key": "rated_burden", "label": "Rated Burden", "type": "number", "unit": "VA"},
                ]
            },
            {
                "title": "Ratio Test Readings",
                "fields": [
                    {
                        "key": "ratio_readings",
                        "label": "Ratio Test Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "primary_current", "label": "Primary (A)", "type": "number"},
                            {"key": "secondary_current", "label": "Secondary (A)", "type": "number"},
                            {"key": "measured_ratio", "label": "Measured Ratio", "type": "number"},
                            {"key": "error_percent", "label": "Error (%)", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Polarity Test",
                "fields": [
                    {"key": "polarity_ok", "label": "Polarity Correct", "type": "boolean", "required": True},
                    {"key": "polarity_method", "label": "Test Method", "type": "dropdown", "options": ["DC Kick Test", "AC Test", "Comparator"]},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 7. Core Insulation Test (Current transformers)
    # ────────────────────────────────────────────────────────────
    "core_insulation_test": {
        "key": "core_insulation_test",
        "name": "Core Insulation Test",
        "equipment_type": "Current Transformer",
        "description": "Core insulation resistance and voltage withstand test",
        "sections": [
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "equipment_make", "label": "Equipment Make", "type": "text", "required": True},
                    {"key": "equipment_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "core_type", "label": "Core Type", "type": "text"},
                    {"key": "test_instrument", "label": "Test Instrument", "type": "text", "required": True},
                ]
            },
            {
                "title": "Core Insulation Readings",
                "fields": [
                    {
                        "key": "core_readings",
                        "label": "Core Insulation Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "core_id", "label": "Core ID", "type": "text"},
                            {"key": "test_voltage", "label": "Test Voltage (V)", "type": "number"},
                            {"key": "ir_value", "label": "IR Value (MOhm)", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 8. Transformer Protection Commissioning (Protection system)
    # ────────────────────────────────────────────────────────────
    "transformer_protection_commissioning": {
        "key": "transformer_protection_commissioning",
        "name": "Transformer Protection Commissioning",
        "equipment_type": "Protection system",
        "description": "Complete transformer protection scheme commissioning",
        "sections": [
            {
                "title": "Transformer Details",
                "fields": [
                    {"key": "transformer_make", "label": "Transformer Make", "type": "text", "required": True},
                    {"key": "transformer_rating", "label": "Transformer Rating", "type": "text", "required": True, "placeholder": "e.g. 10 MVA"},
                    {"key": "voltage_ratio", "label": "Voltage Ratio", "type": "text", "required": True, "placeholder": "e.g. 66/11 kV"},
                    {"key": "vector_group", "label": "Vector Group", "type": "text"},
                ]
            },
            {
                "title": "Protection Scheme Verification",
                "fields": [
                    {
                        "key": "protection_checks",
                        "label": "Protection Checks",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "protection_type", "label": "Protection Type", "type": "text"},
                            {"key": "relay_make_model", "label": "Relay Make/Model", "type": "text"},
                            {"key": "setting_verified", "label": "Setting Verified", "type": "dropdown", "options": ["Yes", "No"]},
                            {"key": "trip_test_ok", "label": "Trip Test OK", "type": "dropdown", "options": ["Yes", "No"]},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Wiring & Panel Checks",
                "fields": [
                    {"key": "ct_wiring_ok", "label": "CT Wiring Correct", "type": "boolean", "required": True},
                    {"key": "pt_wiring_ok", "label": "PT Wiring Correct", "type": "boolean", "required": True},
                    {"key": "trip_circuit_ok", "label": "Trip Circuit OK", "type": "boolean", "required": True},
                    {"key": "alarm_circuit_ok", "label": "Alarm Circuit OK", "type": "boolean"},
                    {"key": "interlock_ok", "label": "Interlocks Verified", "type": "boolean"},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 9. Energy meter accuracy test (Feeder Metering)
    # ────────────────────────────────────────────────────────────
    "energy_meter_accuracy_test": {
        "key": "energy_meter_accuracy_test",
        "name": "Energy meter accuracy test",
        "equipment_type": "Feeder Metering",
        "description": "Energy meter accuracy verification at various load points",
        "sections": [
            {
                "title": "Meter Information",
                "fields": [
                    {"key": "meter_make", "label": "Meter Make", "type": "text", "required": True},
                    {"key": "meter_model", "label": "Meter Model", "type": "text", "required": True},
                    {"key": "meter_serial", "label": "Meter Serial Number", "type": "text", "required": True},
                    {"key": "meter_class", "label": "Accuracy Class", "type": "dropdown", "options": ["0.2", "0.2S", "0.5", "0.5S", "1.0", "2.0"], "required": True},
                    {"key": "rated_voltage", "label": "Rated Voltage", "type": "number", "unit": "V"},
                    {"key": "rated_current", "label": "Rated Current", "type": "number", "unit": "A"},
                    {"key": "reference_standard", "label": "Reference Standard Meter", "type": "text"},
                ]
            },
            {
                "title": "Accuracy Test Readings",
                "fields": [
                    {
                        "key": "accuracy_readings",
                        "label": "Accuracy at Various Loads",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "load_percent", "label": "Load (%)", "type": "number"},
                            {"key": "power_factor", "label": "PF", "type": "number"},
                            {"key": "reference_reading", "label": "Ref Reading", "type": "number"},
                            {"key": "meter_reading", "label": "Meter Reading", "type": "number"},
                            {"key": "error_percent", "label": "Error (%)", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 10. Physical inspection (Transformer)
    # ────────────────────────────────────────────────────────────
    "physical_inspection": {
        "key": "physical_inspection",
        "name": "Physical inspection",
        "equipment_type": "Transformer",
        "description": "Visual and physical condition assessment of transformer",
        "context_bindings": {"location": "nameplate.location", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "location", "label": "Station / Substation", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Transformer Identification",
                "fields": [
                    {"key": "transformer_make", "label": "Transformer Make", "type": "text", "required": True},
                    {"key": "transformer_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "transformer_rating", "label": "Rating", "type": "text", "placeholder": "e.g. 100 kVA"},
                ]
            },
            {
                "title": "External Condition",
                "fields": [
                    {"key": "body_condition", "label": "Body/Tank Condition", "type": "dropdown", "options": ["Good", "Fair", "Poor", "Damaged"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_GFP}},
                    {"key": "paint_condition", "label": "Paint Condition", "type": "dropdown", "options": ["Good", "Faded", "Peeling", "Rusted"], "required": True},
                    {"key": "oil_leak", "label": "Oil Leakage Observed", "type": "boolean", "required": True},
                    {"key": "oil_leak_location", "label": "Leakage Location", "type": "text"},
                    {"key": "oil_level", "label": "Oil Level", "type": "dropdown", "options": ["Normal", "Low", "Very Low", "Empty"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": {"Normal": "NORMAL", "Low": "ALERT", "Very Low": "CRITICAL", "Empty": "CRITICAL"}}},
                    {"key": "oil_color", "label": "Oil Color", "type": "dropdown", "options": ["Clear", "Light Yellow", "Dark Yellow", "Brown", "Black"]},
                    {"key": "silica_gel_condition", "label": "Silica Gel Condition", "type": "dropdown", "options": ["Blue (Good)", "Pink (Saturated)", "Not Available"]},
                ]
            },
            {
                "title": "Bushings & Connections",
                "fields": [
                    {"key": "hv_bushing_condition", "label": "HV Bushing Condition", "type": "dropdown", "options": ["Good", "Cracked", "Chipped", "Damaged"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": {"Good": "NORMAL", "Cracked": "ALERT", "Chipped": "ALERT", "Damaged": "CRITICAL"}}},
                    {"key": "lv_bushing_condition", "label": "LV Bushing Condition", "type": "dropdown", "options": ["Good", "Cracked", "Chipped", "Damaged"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": {"Good": "NORMAL", "Cracked": "ALERT", "Chipped": "ALERT", "Damaged": "CRITICAL"}}},
                    {"key": "terminal_connections", "label": "Terminal Connections", "type": "dropdown", "options": ["Tight", "Loose", "Corroded"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": {"Tight": "NORMAL", "Loose": "ALERT", "Corroded": "CRITICAL"}}},
                    {"key": "earthing_ok", "label": "Earthing Proper", "type": "boolean", "required": True},
                ]
            },
            {
                "title": "Accessories",
                "fields": [
                    {"key": "rating_plate_ok", "label": "Rating Plate Readable", "type": "boolean"},
                    {"key": "thermometer_ok", "label": "Thermometer Working", "type": "boolean"},
                    {"key": "buchholz_relay_ok", "label": "Buchholz Relay OK", "type": "boolean"},
                    {"key": "prv_ok", "label": "PRV/Explosion Vent OK", "type": "boolean"},
                    {"key": "tap_changer_position", "label": "Tap Changer Position", "type": "text"},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks / Observations", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 11. Transformer ratio test (Transformer)
    # ────────────────────────────────────────────────────────────
    "transformer_ratio_test": {
        "key": "transformer_ratio_test",
        "name": "Transformer ratio test",
        "equipment_type": "Transformer",
        "description": "Tap-wise turns ratio measurement of transformer",
        "sections": [
            {
                "title": "Transformer Details",
                "fields": [
                    {"key": "transformer_make", "label": "Transformer Make", "type": "text", "required": True},
                    {"key": "transformer_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "rated_voltage_hv", "label": "Rated Voltage (HV)", "type": "number", "unit": "kV", "required": True},
                    {"key": "rated_voltage_lv", "label": "Rated Voltage (LV)", "type": "number", "unit": "kV", "required": True},
                    {"key": "rated_ratio", "label": "Rated Turns Ratio", "type": "text", "required": True},
                    {"key": "vector_group", "label": "Vector Group", "type": "text", "placeholder": "e.g. Dyn11"},
                    {"key": "number_of_taps", "label": "Number of Taps", "type": "number"},
                ]
            },
            {
                "title": "Tap-wise Ratio Readings",
                "fields": [
                    {
                        "key": "tap_readings",
                        "label": "Tap-wise Ratio Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "tap_position", "label": "Tap Pos", "type": "text"},
                            {"key": "phase_r", "label": "Phase R", "type": "number"},
                            {"key": "phase_y", "label": "Phase Y", "type": "number"},
                            {"key": "phase_b", "label": "Phase B", "type": "number"},
                            {"key": "expected_ratio", "label": "Expected", "type": "number"},
                            {"key": "deviation_percent", "label": "Dev (%)", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "max_deviation", "label": "Max Deviation", "type": "number", "unit": "%"},
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 12. Current ratio test (Transformer)
    # ────────────────────────────────────────────────────────────
    "current_ratio_test": {
        "key": "current_ratio_test",
        "name": "Current ratio test",
        "equipment_type": "Transformer",
        "description": "Current ratio verification at various load points",
        "sections": [
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "equipment_make", "label": "Equipment Make", "type": "text", "required": True},
                    {"key": "equipment_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "rated_ratio", "label": "Rated Current Ratio", "type": "text", "required": True},
                    {"key": "test_instrument", "label": "Test Instrument Used", "type": "text"},
                ]
            },
            {
                "title": "Current Ratio Readings",
                "fields": [
                    {
                        "key": "ratio_readings",
                        "label": "Current Ratio Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "test_point", "label": "Test Point", "type": "text"},
                            {"key": "primary_current", "label": "Primary (A)", "type": "number"},
                            {"key": "secondary_current", "label": "Secondary (A)", "type": "number"},
                            {"key": "measured_ratio", "label": "Ratio", "type": "number"},
                            {"key": "error_percent", "label": "Error (%)", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 13. Short circuit test (Transformer)
    # ────────────────────────────────────────────────────────────
    "short_circuit_test": {
        "key": "short_circuit_test",
        "name": "Short circuit test",
        "equipment_type": "Transformer",
        "description": "Short circuit impedance and copper loss measurement",
        "sections": [
            {
                "title": "Transformer Details",
                "fields": [
                    {"key": "transformer_make", "label": "Transformer Make", "type": "text", "required": True},
                    {"key": "transformer_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "rated_kva", "label": "Rated kVA", "type": "number", "unit": "kVA", "required": True},
                    {"key": "rated_voltage_hv", "label": "Rated Voltage (HV)", "type": "number", "unit": "V", "required": True},
                    {"key": "rated_current_hv", "label": "Rated Current (HV)", "type": "number", "unit": "A", "required": True},
                    {"key": "temperature", "label": "Test Temperature", "type": "number", "unit": "deg C"},
                ]
            },
            {
                "title": "Short Circuit Readings",
                "fields": [
                    {
                        "key": "sc_readings",
                        "label": "Short Circuit Test Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "phase", "label": "Phase", "type": "text"},
                            {"key": "applied_voltage", "label": "Applied V", "type": "number"},
                            {"key": "current", "label": "Current (A)", "type": "number"},
                            {"key": "power", "label": "Power (W)", "type": "number"},
                            {"key": "impedance_percent", "label": "Z (%)", "type": "number"}
                        ]
                    }
                ]
            },
            {
                "title": "Calculated Values",
                "fields": [
                    {"key": "impedance_voltage", "label": "Impedance Voltage", "type": "number", "unit": "%"},
                    {"key": "copper_loss", "label": "Copper Loss", "type": "number", "unit": "W"},
                    {"key": "winding_resistance_hv", "label": "Winding Resistance (HV)", "type": "number", "unit": "ohms"},
                    {"key": "winding_resistance_lv", "label": "Winding Resistance (LV)", "type": "number", "unit": "ohms"},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 14. Open circuit test (Transformer)
    # ────────────────────────────────────────────────────────────
    "open_circuit_test": {
        "key": "open_circuit_test",
        "name": "Open circuit test",
        "equipment_type": "Transformer",
        "description": "No-load current and iron loss measurement",
        "sections": [
            {
                "title": "Transformer Details",
                "fields": [
                    {"key": "transformer_make", "label": "Transformer Make", "type": "text", "required": True},
                    {"key": "transformer_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "rated_kva", "label": "Rated kVA", "type": "number", "unit": "kVA", "required": True},
                    {"key": "rated_voltage_lv", "label": "Rated Voltage (LV)", "type": "number", "unit": "V", "required": True},
                ]
            },
            {
                "title": "Open Circuit Readings",
                "fields": [
                    {
                        "key": "oc_readings",
                        "label": "Open Circuit Test Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "phase", "label": "Phase", "type": "text"},
                            {"key": "applied_voltage", "label": "Applied V", "type": "number"},
                            {"key": "no_load_current", "label": "No-Load I (A)", "type": "number"},
                            {"key": "power", "label": "Power (W)", "type": "number"}
                        ]
                    }
                ]
            },
            {
                "title": "Calculated Values",
                "fields": [
                    {"key": "no_load_current_percent", "label": "No-Load Current", "type": "number", "unit": "% of rated"},
                    {"key": "iron_loss", "label": "Iron Loss (Core Loss)", "type": "number", "unit": "W"},
                    {"key": "magnetizing_current", "label": "Magnetizing Current", "type": "number", "unit": "A"},
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 15. Magnetic balance test (Transformer)
    # ────────────────────────────────────────────────────────────
    "magnetic_balance_test": {
        "key": "magnetic_balance_test",
        "name": "Magnetic balance test",
        "equipment_type": "Transformer",
        "description": "Phase-wise magnetic balance verification",
        "sections": [
            {
                "title": "Transformer Details",
                "fields": [
                    {"key": "transformer_make", "label": "Transformer Make", "type": "text", "required": True},
                    {"key": "transformer_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "rated_kva", "label": "Rated kVA", "type": "number", "unit": "kVA", "required": True},
                    {"key": "test_voltage", "label": "Test Voltage Applied", "type": "number", "unit": "V", "required": True},
                ]
            },
            {
                "title": "Magnetic Balance Readings",
                "fields": [
                    {
                        "key": "balance_readings",
                        "label": "Magnetic Balance Readings",
                        "type": "table",
                        "required": True,
                        "columns": [
                            {"key": "excitation_phase", "label": "Excited Phase", "type": "text"},
                            {"key": "voltage_phase_1", "label": "V Phase 1 (V)", "type": "number"},
                            {"key": "voltage_phase_2", "label": "V Phase 2 (V)", "type": "number"},
                            {"key": "voltage_phase_3", "label": "V Phase 3 (V)", "type": "number"},
                            {"key": "balance_ratio", "label": "Balance (%)", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "max_imbalance", "label": "Max Imbalance", "type": "number", "unit": "%"},
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True, "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFCR}},
                ]
            }
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 16. Meter Testing (Meter)
    # ────────────────────────────────────────────────────────────
    "meter_testing": {
        "key": "meter_testing",
        "name": "Meter Testing",
        "equipment_type": "Electronic Tri-vector Meter",
        "description": "Testing of energy meters at substations",
        "context_bindings": {
            "station_name": "equipment.department_name",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                ],
            },
            {
                "title": "Meter Test Readings",
                "fields": [
                    {
                        "key": "meter_readings",
                        "label": "Meter Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "feeder_name", "label": "Feeder Name", "type": "text"},
                            {"key": "cctr", "label": "CCTR", "type": "text"},
                            {"key": "make", "label": "Make", "type": "text"},
                            {"key": "pulse", "label": "Pulse", "type": "text"},
                            {"key": "ctr", "label": "CTR", "type": "text"},
                            {"key": "ptr", "label": "PTR", "type": "text"},
                            {"key": "acc_cl", "label": "ACC CL", "type": "text"},
                            {"key": "mc", "label": "MC", "type": "text"},
                            {"key": "power", "label": "Power", "type": "text"},
                            {"key": "l1", "label": "L1", "type": "number"},
                            {"key": "v1", "label": "V1", "type": "number"},
                            {"key": "l2", "label": "L2", "type": "number"},
                            {"key": "v2", "label": "V2", "type": "number"},
                            {"key": "l3", "label": "L3", "type": "number"},
                            {"key": "v3", "label": "V3", "type": "number"},
                            {"key": "pf", "label": "PF", "type": "number"},
                            {"key": "freq", "label": "F", "type": "number"},
                            {"key": "error_pct", "label": "% Error", "type": "number"},
                            {"key": "remarks", "label": "Remarks", "type": "text"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 17. Relay Testing (Relay)
    # ────────────────────────────────────────────────────────────
    "relay_testing": {
        "key": "relay_testing",
        "name": "Relay Testing",
        "equipment_type": "Protection Relay",
        "description": "Testing of relays at substations with phase-wise readings",
        "context_bindings": {
            "station_name": "equipment.department_name",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                ],
            },
            {
                "title": "Relay Test Readings",
                "fields": [
                    {
                        "key": "relay_readings",
                        "label": "Relay Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "feeder_name", "label": "Feeder Name", "type": "text"},
                            {"key": "panel_make", "label": "Panel Make", "type": "text"},
                            {"key": "panel_type", "label": "Panel Type", "type": "text"},
                            {"key": "panel_sl_no", "label": "Panel SL No", "type": "text"},
                            {"key": "ct_ratio", "label": "CT Ratio", "type": "text"},
                            {"key": "phase", "label": "Phase", "type": "text"},
                            {"key": "ct_setting", "label": "CT Setting", "type": "text"},
                            {"key": "tl_setting", "label": "TL Setting", "type": "text"},
                            {"key": "test_current", "label": "Test Current (A)", "type": "number"},
                            {"key": "trip_time", "label": "Trip Time (sec)", "type": "number"},
                            {"key": "pick_up", "label": "Pick Up", "type": "text"},
                            {"key": "target", "label": "Target", "type": "text"},
                            {"key": "hs", "label": "H/S", "type": "text"},
                            {"key": "remarks", "label": "Remarks", "type": "text"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 18. Power Transformer Nameplate Details (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "power_transformer_nameplate": {
        "key": "power_transformer_nameplate",
        "name": "Power Transformer Test Report",
        "equipment_type": "Power Transformer",
        "description": "Power transformer nameplate details and OLTC details",
        "context_bindings": {
            "location":           "nameplate.location",
            "make":               "equipment.manufacturer",
            "rated_mva":          "nameplate.rated_mva",
            "rated_voltage":      "equipment.voltage_class",
            "rated_current":      "nameplate.rated_current",
            "rated_insulation":   "nameplate.rated_insulation",
            "frequency":          "nameplate.frequency",
            "vector_group":       "equipment.vector_group",
            "impedance_voltage":  "nameplate.impedance_voltage",
            "sl_no":              "equipment.factory_serial_number",
            "type_of_cooling":    "nameplate.type_of_cooling",
            "yom":                "nameplate.yom",
            "date_of_commission": "nameplate.date_of_commission",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "location", "label": "Station / Substation", "type": "readonly"},
                    {"key": "make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "rated_mva", "label": "Rated MVA", "type": "readonly"},
                    {"key": "rated_voltage", "label": "Voltage Class", "type": "readonly"},
                    {"key": "rated_current", "label": "Rated Current", "type": "readonly"},
                    {"key": "rated_insulation", "label": "Rated Insulation", "type": "readonly"},
                    {"key": "frequency", "label": "Frequency", "type": "readonly"},
                    {"key": "vector_group", "label": "Vector Group", "type": "readonly"},
                    {"key": "impedance_voltage", "label": "Impedance Voltage", "type": "readonly"},
                    {"key": "sl_no", "label": "Serial Number", "type": "readonly"},
                    {"key": "type_of_cooling", "label": "Type of Cooling", "type": "readonly"},
                    {"key": "yom", "label": "Year of Manufacture", "type": "readonly"},
                    {"key": "date_of_commission", "label": "Date of Commission", "type": "readonly"},
                ],
            },
            {
                "title": "Transformer Nameplate Details",
                "fields": [
                    {"key": "tr_class", "label": "Class", "type": "text"},
                    {"key": "phases_hv_iv_lv", "label": "Phases HV/IV/LV", "type": "text"},
                    {"key": "total_mass", "label": "Total Mass", "type": "text", "unit": "kg"},
                    {"key": "transport_mass", "label": "Transport Mass", "type": "text", "unit": "kg"},
                    {"key": "untanking_mass", "label": "Untanking Mass", "type": "text", "unit": "kg"},
                    {"key": "insulating_oil_mass", "label": "Insulating Oil Mass", "type": "text", "unit": "kg"},
                    {"key": "insulating_oil_ltrs", "label": "Insulating Oil", "type": "text", "unit": "ltrs"},
                    {"key": "max_oil_temp_rise", "label": "Max Oil Temperature Rise", "type": "text", "unit": "°C"},
                    {"key": "winding_temp_rise", "label": "Winding Temperature Rise", "type": "text", "unit": "°C"},
                    {"key": "top_oil_temp_rise", "label": "Top Oil Temperature Rise", "type": "text", "unit": "°C"},
                    {"key": "sym_short_circuit_current", "label": "Symmetrical Short Circuit Current", "type": "text", "unit": "kA"},
                    {"key": "max_sc_duration", "label": "Max Short Circuit Duration", "type": "text"},
                    {"key": "lo_of_keb", "label": "L.O of KEB", "type": "text"},
                    {"key": "date_of_order", "label": "Date of Order", "type": "date"},
                    {"key": "date_of_testing_maker", "label": "Date of Testing by Maker", "type": "date"},
                    {"key": "taps_on_hv", "label": "Taps available on HV", "type": "text"},
                    {"key": "specification", "label": "Specification", "type": "text"},
                ]
            },
            {
                "title": "OLTC Nameplate Details",
                "fields": [
                    {"key": "oltc_make", "label": "OLTC Make", "type": "text"},
                    {"key": "oltc_sl_no_yom", "label": "OLTC Sl No & YOM", "type": "text"},
                    {"key": "oltc_type", "label": "OLTC Type", "type": "text"},
                    {"key": "oltc_transition_resistance", "label": "Transition Resistance", "type": "text"},
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 19. Transformer Physical Inspection (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "transformer_physical_inspection": {
        "key": "transformer_physical_inspection",
        "name": "Transformer Physical Inspection",
        "equipment_type": "Power Transformer",
        "description": "Physical inspection and megger test results for power transformers",
        "context_bindings": {"manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number", "voltage_class": "equipment.voltage_class", "vector_group": "equipment.vector_group"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                {"key": "voltage_class", "label": "Voltage Class", "type": "readonly"},
                {"key": "vector_group", "label": "Vector Group", "type": "readonly"},
                ],
            },
            {
                "title": "Physical Inspection",
                "fields": [
                    {"key": "physical_appearance", "label": "Physical Appearance", "type": "textarea"},
                    {"key": "air_released_hv_bushings", "label": "Air released in HV Bushings", "type": "textarea"},
                    {"key": "air_released_lv_bushings", "label": "Air released in LV Bushings", "type": "textarea"},
                    {"key": "air_released_buchholz", "label": "Air released in Buchholz Relay", "type": "textarea"},
                ]
            },
            {
                "title": "Megger Test Information",
                "fields": [
                    {"key": "megger_class", "label": "Megger Used (Class)", "type": "text"},
                    {"key": "oil_temperature", "label": "Oil Temperature", "type": "text"},
                    {"key": "winding_temperature", "label": "Winding Temperature", "type": "text"},
                    {"key": "hv_iv_lv_continuity", "label": "HV / IV / LV Continuity", "type": "text"},
                ]
            },
            {
                "title": "Insulation Resistance Test Results",
                "fields": [
                    {
                        "key": "ir_test_results",
                        "label": "Insulation Resistance Readings",
                        "type": "table",
                        "columns": [
                            {"key": "test", "label": "Test", "type": "text"},
                            {"key": "value_20sec", "label": "20 sec", "type": "number"},
                            {"key": "value_120sec", "label": "120 sec", "type": "number"},
                            {"key": "unit", "label": "Unit", "type": "text"},
                            {"key": "pi_value", "label": "P.I (120s/20s)", "type": "number"},
                        ],
                        "default_rows": [
                            {"test": "HV to Ground"},
                            {"test": "IV to Ground"},
                            {"test": "LV to Ground"},
                            {"test": "HV to IV"},
                            {"test": "HV to LV"},
                            {"test": "IV to LV"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 20. Ratio Test HV-IV (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "ratio_test_hv_iv": {
        "key": "ratio_test_hv_iv",
        "name": "Ratio Test HV-IV",
        "equipment_type": "Power Transformer",
        "description": "Ratio test results between HV and IV windings",
        "sections": [
            {
                "title": "Ratio Test Readings (HV & IV)",
                "fields": [
                    {
                        "key": "ratio_readings",
                        "label": "Ratio Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                            {"key": "applied_ry", "label": "Applied V (RY)", "type": "number"},
                            {"key": "applied_yb", "label": "Applied V (YB)", "type": "number"},
                            {"key": "applied_br", "label": "Applied V (BR)", "type": "number"},
                            {"key": "induced_rv", "label": "Induced V (rv)", "type": "number"},
                            {"key": "induced_vb", "label": "Induced V (vb)", "type": "number"},
                            {"key": "induced_br", "label": "Induced V (br)", "type": "number"},
                            {"key": "induced_rn", "label": "Induced V (rn)", "type": "number"},
                            {"key": "induced_yn", "label": "Induced V (yn)", "type": "number"},
                            {"key": "induced_bn", "label": "Induced V (bn)", "type": "number"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 21. Ratio Test HV-LV (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "ratio_test_hv_lv": {
        "key": "ratio_test_hv_lv",
        "name": "Ratio Test HV-LV",
        "equipment_type": "Power Transformer",
        "description": "Ratio test results between HV and LV windings",
        "sections": [
            {
                "title": "Ratio Test Readings (HV & LV)",
                "fields": [
                    {
                        "key": "ratio_readings",
                        "label": "Ratio Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                            {"key": "applied_ry", "label": "Applied V (RY)", "type": "number"},
                            {"key": "applied_yb", "label": "Applied V (YB)", "type": "number"},
                            {"key": "applied_br", "label": "Applied V (BR)", "type": "number"},
                            {"key": "induced_rv", "label": "Induced V (rv)", "type": "number"},
                            {"key": "induced_yb", "label": "Induced V (yb)", "type": "number"},
                            {"key": "induced_br", "label": "Induced V (br)", "type": "number"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 22. Short Circuit Test HV-IV (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "short_circuit_test_hv_iv": {
        "key": "short_circuit_test_hv_iv",
        "name": "Short Circuit Test HV-IV",
        "equipment_type": "Power Transformer",
        "description": "Short circuit test results between HV and IV windings",
        "sections": [
            {
                "title": "Short Circuit Test Readings (HV & IV)",
                "fields": [
                    {
                        "key": "sc_readings",
                        "label": "Short Circuit Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                            {"key": "applied_ry", "label": "Applied V (RY)", "type": "number"},
                            {"key": "applied_yb", "label": "Applied V (YB)", "type": "number"},
                            {"key": "applied_br", "label": "Applied V (BR)", "type": "number"},
                            {"key": "current_r", "label": "HV Current R (A)", "type": "number"},
                            {"key": "current_y", "label": "HV Current Y (A)", "type": "number"},
                            {"key": "current_b", "label": "HV Current B (A)", "type": "number"},
                            {"key": "in_iv_side", "label": "In on IV side (mA)", "type": "number"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 23. Short Circuit Test HV-LV (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "short_circuit_test_hv_lv": {
        "key": "short_circuit_test_hv_lv",
        "name": "Short Circuit Test HV-LV",
        "equipment_type": "Power Transformer",
        "description": "Short circuit test results between HV and LV windings",
        "sections": [
            {
                "title": "Short Circuit Test Readings (HV & LV)",
                "fields": [
                    {
                        "key": "sc_readings",
                        "label": "Short Circuit Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                            {"key": "applied_ry", "label": "Applied V (RY)", "type": "number"},
                            {"key": "applied_yb", "label": "Applied V (YB)", "type": "number"},
                            {"key": "applied_br", "label": "Applied V (BR)", "type": "number"},
                            {"key": "current_r", "label": "HV Current R (A)", "type": "number"},
                            {"key": "current_y", "label": "HV Current Y (A)", "type": "number"},
                            {"key": "current_b", "label": "HV Current B (A)", "type": "number"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 24. Magnetic Balance Test HV (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "magnetic_balance_test_hv": {
        "key": "magnetic_balance_test_hv",
        "name": "Magnetic Balance Test HV",
        "equipment_type": "Power Transformer",
        "description": "Magnetic balance test results on HV side",
        "sections": [
            {
                "title": "Magnetic Balance Test (HV Side)",
                "fields": [
                    {
                        "key": "mb_readings",
                        "label": "Voltage Readings",
                        "type": "table",
                        "columns": [
                            {"key": "voltage_applied_on", "label": "Voltage Applied On", "type": "text"},
                            {"key": "rn_v", "label": "RN (V)", "type": "number"},
                            {"key": "yn_v", "label": "YN (V)", "type": "number"},
                            {"key": "bn_v", "label": "BN (V)", "type": "number"},
                        ],
                        "default_rows": [
                            {"voltage_applied_on": "RN"},
                            {"voltage_applied_on": "YN"},
                            {"voltage_applied_on": "BN"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 25. Magnetic Balance Test IV (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "magnetic_balance_test_iv": {
        "key": "magnetic_balance_test_iv",
        "name": "Magnetic Balance Test IV",
        "equipment_type": "Power Transformer",
        "description": "Magnetic balance test results on IV side",
        "sections": [
            {
                "title": "Magnetic Balance Test (IV Side)",
                "fields": [
                    {
                        "key": "mb_readings",
                        "label": "Voltage Readings",
                        "type": "table",
                        "columns": [
                            {"key": "voltage_applied_on", "label": "Voltage Applied On", "type": "text"},
                            {"key": "rn_v", "label": "rn (V)", "type": "number"},
                            {"key": "yn_v", "label": "yn (V)", "type": "number"},
                            {"key": "bn_v", "label": "bn (V)", "type": "number"},
                        ],
                        "default_rows": [
                            {"voltage_applied_on": "RN"},
                            {"voltage_applied_on": "YN"},
                            {"voltage_applied_on": "BN"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 26. Magnetic Balance Test LV (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "magnetic_balance_test_lv": {
        "key": "magnetic_balance_test_lv",
        "name": "Magnetic Balance Test LV",
        "equipment_type": "Power Transformer",
        "description": "Magnetic balance test results on LV side",
        "sections": [
            {
                "title": "Magnetic Balance Test (LV Side)",
                "fields": [
                    {
                        "key": "mb_readings",
                        "label": "Voltage Readings",
                        "type": "table",
                        "columns": [
                            {"key": "voltage_applied_on", "label": "Voltage Applied On", "type": "text"},
                            {"key": "ry_v", "label": "ry (V)", "type": "number"},
                            {"key": "yb_v", "label": "yb (V)", "type": "number"},
                            {"key": "br_v", "label": "br (V)", "type": "number"},
                        ],
                        "default_rows": [
                            {"voltage_applied_on": "RN"},
                            {"voltage_applied_on": "YN"},
                            {"voltage_applied_on": "BN"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 27-32. Open Circuit Tests (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "open_circuit_test_hv_iv_1ph": {
        "key": "open_circuit_test_hv_iv_1ph",
        "name": "Open Circuit Test HV-IV (1Ph)",
        "equipment_type": "Power Transformer",
        "description": "HV & IV open circuit test results at 1 Phase 400V",
        "sections": [
            {
                "title": "Open Circuit Test Readings (HV-IV, 1Ph 400V)",
                "fields": [
                    {
                        "key": "oc_readings",
                        "label": "Open Circuit Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                            {"key": "applied_ry", "label": "Applied V (ry)", "type": "number"},
                            {"key": "applied_yb", "label": "Applied V (yb)", "type": "number"},
                            {"key": "applied_br", "label": "Applied V (br)", "type": "number"},
                            {"key": "current_r", "label": "Current R (mA)", "type": "number"},
                            {"key": "current_y", "label": "Current Y (mA)", "type": "number"},
                            {"key": "current_b", "label": "Current B (mA)", "type": "number"},
                        ]
                    }
                ]
            },
        ]
    },
    "open_circuit_test_hv_iv_3ph": {
        "key": "open_circuit_test_hv_iv_3ph",
        "name": "Open Circuit Test HV-IV (3Ph)",
        "equipment_type": "Power Transformer",
        "description": "HV & IV open circuit test results at 3 Phase 400V",
        "sections": [
            {"title": "Open Circuit Test Readings (HV-IV, 3Ph 400V)", "fields": [
                {"key": "oc_readings", "label": "Open Circuit Test Readings", "type": "table", "columns": [
                    {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                    {"key": "applied_ry", "label": "Applied V (ry)", "type": "number"},
                    {"key": "applied_yb", "label": "Applied V (yb)", "type": "number"},
                    {"key": "applied_br", "label": "Applied V (br)", "type": "number"},
                    {"key": "current_r", "label": "Current R (mA)", "type": "number"},
                    {"key": "current_y", "label": "Current Y (mA)", "type": "number"},
                    {"key": "current_b", "label": "Current B (mA)", "type": "number"},
                ]}
            ]}
        ]
    },
    "open_circuit_test_hv_lv_1ph": {
        "key": "open_circuit_test_hv_lv_1ph",
        "name": "Open Circuit Test HV-LV (1Ph)",
        "equipment_type": "Power Transformer",
        "description": "HV & LV open circuit test results at 1 Phase 400V",
        "sections": [
            {"title": "Open Circuit Test Readings (HV-LV, 1Ph 400V)", "fields": [
                {"key": "oc_readings", "label": "Open Circuit Test Readings", "type": "table", "columns": [
                    {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                    {"key": "applied_ry", "label": "Applied V (ry)", "type": "number"},
                    {"key": "applied_yb", "label": "Applied V (yb)", "type": "number"},
                    {"key": "applied_br", "label": "Applied V (br)", "type": "number"},
                    {"key": "current_r", "label": "Current R (mA)", "type": "number"},
                    {"key": "current_y", "label": "Current Y (mA)", "type": "number"},
                    {"key": "current_b", "label": "Current B (mA)", "type": "number"},
                ]}
            ]}
        ]
    },
    "open_circuit_test_hv_lv_3ph": {
        "key": "open_circuit_test_hv_lv_3ph",
        "name": "Open Circuit Test HV-LV (3Ph)",
        "equipment_type": "Power Transformer",
        "description": "HV & LV open circuit test results at 3 Phase 400V",
        "sections": [
            {"title": "Open Circuit Test Readings (HV-LV, 3Ph 400V)", "fields": [
                {"key": "oc_readings", "label": "Open Circuit Test Readings", "type": "table", "columns": [
                    {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                    {"key": "applied_ry", "label": "Applied V (ry)", "type": "number"},
                    {"key": "applied_yb", "label": "Applied V (yb)", "type": "number"},
                    {"key": "applied_br", "label": "Applied V (br)", "type": "number"},
                    {"key": "current_r", "label": "Current R (mA)", "type": "number"},
                    {"key": "current_y", "label": "Current Y (mA)", "type": "number"},
                    {"key": "current_b", "label": "Current B (mA)", "type": "number"},
                ]}
            ]}
        ]
    },
    "open_circuit_test_iv_lv_1ph": {
        "key": "open_circuit_test_iv_lv_1ph",
        "name": "Open Circuit Test IV-LV (1Ph)",
        "equipment_type": "Power Transformer",
        "description": "IV & LV open circuit test results at 1 Phase 400V",
        "sections": [
            {"title": "Open Circuit Test Readings (IV-LV, 1Ph 400V)", "fields": [
                {"key": "oc_readings", "label": "Open Circuit Test Readings", "type": "table", "columns": [
                    {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                    {"key": "applied_ry", "label": "Applied V (ry)", "type": "number"},
                    {"key": "applied_yb", "label": "Applied V (yb)", "type": "number"},
                    {"key": "applied_br", "label": "Applied V (br)", "type": "number"},
                    {"key": "current_r", "label": "Current R (mA)", "type": "number"},
                    {"key": "current_y", "label": "Current Y (mA)", "type": "number"},
                    {"key": "current_b", "label": "Current B (mA)", "type": "number"},
                ]}
            ]}
        ]
    },
    "open_circuit_test_iv_lv_3ph": {
        "key": "open_circuit_test_iv_lv_3ph",
        "name": "Open Circuit Test IV-LV (3Ph)",
        "equipment_type": "Power Transformer",
        "description": "IV & LV open circuit test results at 3 Phase 400V",
        "sections": [
            {"title": "Open Circuit Test Readings (IV-LV, 3Ph 400V)", "fields": [
                {"key": "oc_readings", "label": "Open Circuit Test Readings", "type": "table", "columns": [
                    {"key": "oltc_tap", "label": "OLTC Tap Position", "type": "text"},
                    {"key": "applied_ry", "label": "Applied V (ry)", "type": "number"},
                    {"key": "applied_yb", "label": "Applied V (yb)", "type": "number"},
                    {"key": "applied_br", "label": "Applied V (br)", "type": "number"},
                    {"key": "current_r", "label": "Current R (mA)", "type": "number"},
                    {"key": "current_y", "label": "Current Y (mA)", "type": "number"},
                    {"key": "current_b", "label": "Current B (mA)", "type": "number"},
                ]}
            ]}
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 33. CT Insulation Test (Current Transformer)
    # ────────────────────────────────────────────────────────────
    "ct_insulation_test": {
        "key": "ct_insulation_test",
        "name": "CT Insulation Test",
        "equipment_type": "Current Transformer",
        "description": "Current transformer insulation test report with nameplate and IR measurements",
        "context_bindings": {
            "station_name": "equipment.department_name",
            "ct_make":      "equipment.manufacturer",
            "ct_sl_no":     "equipment.factory_serial_number",
            "ct_yom":       "nameplate.yom",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "ct_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "ct_sl_no", "label": "Serial Number", "type": "readonly"},
                    {"key": "ct_yom", "label": "Year of Manufacture", "type": "readonly"},
                ],
            },
            {
                "title": "CT Details",
                "fields": [
                    {"key": "bay_name", "label": "Bay Name", "type": "text", "required": True},
                    {"key": "actr", "label": "ACTR", "type": "text"},
                    {"key": "core1_burden", "label": "Core 1 Burden", "type": "text"},
                    {"key": "core2_burden", "label": "Core 2 Burden", "type": "text"},
                    {"key": "core3_burden", "label": "Core 3 Burden", "type": "text"},
                    {"key": "core4_burden", "label": "Core 4 Burden", "type": "text"},
                    {"key": "core5_burden", "label": "Core 5 Burden", "type": "text"},
                    {"key": "core6_burden", "label": "Core 6 Burden", "type": "text"},
                    {"key": "highest_system_voltage", "label": "Highest System Voltage", "type": "text"},
                    {"key": "insulation_level", "label": "Insulation Level", "type": "text"},
                    {"key": "stc", "label": "STC", "type": "text"},
                ]
            },
            {
                "title": "Insulation Resistance Measurement",
                "fields": [
                    {
                        "key": "ir_readings",
                        "label": "Insulation Resistance Readings",
                        "type": "table",
                        "columns": [
                            {"key": "test", "label": "Test", "type": "text"},
                            {"key": "megger_used", "label": "Megger Used", "type": "text"},
                            {"key": "r_phase", "label": "R Phase", "type": "number"},
                            {"key": "b_phase", "label": "B Phase", "type": "number"},
                        ],
                        "default_rows": [
                            {"test": "HV to GND"},
                            {"test": "HV to Core-1"},
                            {"test": "HV to Core-2"},
                            {"test": "HV to Core-3"},
                            {"test": "HV to Core-4"},
                            {"test": "HV to Core-5"},
                            {"test": "HV to Core-6"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 34. CT Ratio Test Detailed (Current Transformer)
    # ────────────────────────────────────────────────────────────
    "ct_ratio_test_detailed": {
        "key": "ct_ratio_test_detailed",
        "name": "CT Ratio Test (Detailed)",
        "equipment_type": "Current Transformer",
        "description": "Detailed CT ratio test with phase-wise readings across multiple cores",
        "context_bindings": {
            "station_name": "equipment.department_name",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                ],
            },
            {
                "title": "Test Information",
                "fields": [
                    {"key": "bay_name", "label": "Bay Name", "type": "text", "required": True},
                    {"key": "polarity", "label": "Polarity", "type": "text"},
                ]
            },
            {
                "title": "R Phase CT Ratio Readings",
                "fields": [
                    {
                        "key": "r_phase_readings",
                        "label": "R Phase Readings",
                        "type": "table",
                        "columns": [
                            {"key": "injected_current", "label": "Injected Current (A)", "type": "number"},
                            {"key": "to_be", "label": "To Be", "type": "number"},
                            {"key": "core1", "label": "Core 1", "type": "number"},
                            {"key": "core2", "label": "Core 2", "type": "number"},
                            {"key": "core3", "label": "Core 3", "type": "number"},
                            {"key": "core4", "label": "Core 4", "type": "number"},
                            {"key": "core5", "label": "Core 5", "type": "number"},
                            {"key": "core6", "label": "Core 6", "type": "number"},
                        ]
                    }
                ]
            },
            {
                "title": "B Phase CT Ratio Readings",
                "fields": [
                    {
                        "key": "b_phase_readings",
                        "label": "B Phase Readings",
                        "type": "table",
                        "columns": [
                            {"key": "injected_current", "label": "Injected Current (A)", "type": "number"},
                            {"key": "to_be", "label": "To Be", "type": "number"},
                            {"key": "core1", "label": "Core 1", "type": "number"},
                            {"key": "core2", "label": "Core 2", "type": "number"},
                            {"key": "core3", "label": "Core 3", "type": "number"},
                            {"key": "core4", "label": "Core 4", "type": "number"},
                            {"key": "core5", "label": "Core 5", "type": "number"},
                            {"key": "core6", "label": "Core 6", "type": "number"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 35. CVT Test Report (CVT)
    # ────────────────────────────────────────────────────────────
    "cvt_test": {
        "key": "cvt_test",
        "name": "CVT Test Report",
        "equipment_type": "Capacitor Voltage Transformer",
        "description": "CVT test report with details, insulation resistance, and ratio test",
        "context_bindings": {
            "station_name": "equipment.department_name",
            "cvt_make":     "equipment.manufacturer",
            "cvt_sl_no":    "equipment.factory_serial_number",
            "cvt_yom":      "nameplate.yom",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "cvt_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "cvt_sl_no", "label": "Serial Number", "type": "readonly"},
                    {"key": "cvt_yom", "label": "Year of Manufacture", "type": "readonly"},
                ],
            },
            {
                "title": "CVT Details",
                "fields": [
                    {"key": "bay_name", "label": "Bay Name", "type": "text", "required": True},
                    {"key": "core1_burden", "label": "Core 1 - Burden", "type": "text"},
                    {"key": "core1_class", "label": "Core 1 - Class", "type": "text"},
                    {"key": "core2_burden", "label": "Core 2 - Burden", "type": "text"},
                    {"key": "core2_class", "label": "Core 2 - Class", "type": "text"},
                    {"key": "core3_burden", "label": "Core 3 - Burden", "type": "text"},
                    {"key": "core3_class", "label": "Core 3 - Class", "type": "text"},
                    {"key": "insulation", "label": "Insulation", "type": "text"},
                    {"key": "cvt_type", "label": "Type", "type": "text"},
                ]
            },
            {
                "title": "Insulation Resistance Measurement",
                "fields": [
                    {
                        "key": "ir_readings",
                        "label": "IR Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "test", "label": "Test", "type": "text"},
                            {"key": "megger_used", "label": "Megger Used", "type": "text"},
                            {"key": "r_phase", "label": "R Phase", "type": "number"},
                            {"key": "b_phase", "label": "B Phase", "type": "number"},
                        ],
                        "default_rows": [
                            {"test": "HV to GND"},
                            {"test": "HV to Core-1"},
                            {"test": "HV to Core-2"},
                        ]
                    }
                ]
            },
            {
                "title": "Ratio Test",
                "fields": [
                    {
                        "key": "ratio_readings",
                        "label": "Ratio Test Readings",
                        "type": "table",
                        "columns": [
                            {"key": "applied_voltage", "label": "Applied Voltage", "type": "number"},
                            {"key": "to_be", "label": "To Be", "type": "number"},
                            {"key": "r_1a_1n", "label": "R Phase 1a-1n", "type": "number"},
                            {"key": "r_2a_2n", "label": "R Phase 2a-2n", "type": "number"},
                            {"key": "b_1a_1n", "label": "B Phase 1a-1n", "type": "number"},
                            {"key": "b_2a_2n", "label": "B Phase 2a-2n", "type": "number"},
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 36. Capacitance & Tan Delta Test CT (Current Transformer)
    # ────────────────────────────────────────────────────────────
    "capacitance_tandelta_ct": {
        "key": "capacitance_tandelta_ct",
        "name": "Capacitance & Tan Delta Test (CT)",
        "equipment_type": "Current Transformer",
        "description": "Capacitance and tan delta test results for current transformers",
        "context_bindings": {
            "station_name": "equipment.department_name",
            "ct_make":      "equipment.manufacturer",
            "ct_sl_no":     "equipment.factory_serial_number",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "ct_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "ct_sl_no", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Test Information",
                "fields": [
                    {"key": "bay_name", "label": "Bay Name", "type": "text"},
                ]
            },
            {
                "title": "Capacitance & Tan Delta Readings",
                "fields": [
                    {
                        "key": "tandelta_readings",
                        "label": "Capacitance & Tan Delta Readings",
                        "type": "table",
                        "columns": [
                            {"key": "details", "label": "Details", "type": "text"},
                            {"key": "freq_hz", "label": "f (Hz)", "type": "number"},
                            {"key": "voltage_kv", "label": "U (kV)", "type": "number"},
                            {"key": "r_current", "label": "R-ph I (mA)", "type": "number"},
                            {"key": "r_cap", "label": "R-ph C (pF)", "type": "number"},
                            {"key": "r_tandelta", "label": "R-ph %TanD", "type": "number"},
                            {"key": "y_current", "label": "Y-ph I (mA)", "type": "number"},
                            {"key": "y_cap", "label": "Y-ph C (pF)", "type": "number"},
                            {"key": "y_tandelta", "label": "Y-ph %TanD", "type": "number"},
                            {"key": "b_current", "label": "B-ph I (mA)", "type": "number"},
                            {"key": "b_cap", "label": "B-ph C (pF)", "type": "number"},
                            {"key": "b_tandelta", "label": "B-ph %TanD", "type": "number"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "r_tandelta",
                                        "thresholds": {
                                            "CT % Tan Delta (IEC 60044-1)": {
                                                "Good": [None, 0.5],
                                                "Fair": [0.5,  1.0],
                                                "Poor": [1.0,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 38. Capacitance & Tan Delta Comparison (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "tandelta_comparison": {
        "key": "tandelta_comparison",
        "name": "Capacitance & Tan Delta Comparison",
        "equipment_type": "Power Transformer",
        "description": "Comparison of capacitance and tan delta values across transformer bushings and CTs",
        "context_bindings": {
            "station_name": "nameplate.location",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                ],
            },
            {
                "title": "Comparison Values",
                "fields": [
                    {
                        "key": "comparison_values",
                        "label": "Comparison of Capacitance & Tan Delta Values",
                        "type": "table",
                        "columns": [
                            {"key": "bay_name", "label": "Bay Name", "type": "text"},
                            {"key": "phase", "label": "Phase", "type": "text"},
                            {"key": "capacitance_pf", "label": "Capacitance (pF)", "type": "number"},
                            {"key": "tandelta_pct", "label": "tan δ (%)", "type": "number"},
                            {"key": "tandelta_temp_corrected", "label": "tan δ Temp Corrected (%)", "type": "number"},
                            {"key": "remarks", "label": "Remarks", "type": "text"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "tandelta_temp_corrected",
                                        "thresholds": {
                                            "tan δ @ 20°C (IEC)": {
                                                "Good": [None, 0.5],
                                                "Fair": [0.5,  1.0],
                                                "Poor": [1.0,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 39. Tan Delta NCT Test (Current Transformer)
    # ────────────────────────────────────────────────────────────
    "tandelta_nct": {
        "key": "tandelta_nct",
        "name": "Tan Delta NCT Test",
        "equipment_type": "Current Transformer",
        "description": "Capacitance and tan delta results for neutral current transformers",
        "context_bindings": {
            "station_name": "equipment.department_name",
            "nct_make":     "equipment.manufacturer",
            "nct_sl_no":    "equipment.factory_serial_number",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "nct_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "nct_sl_no", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "NCT Tan Delta Readings",
                "fields": [
                    {
                        "key": "nct_readings",
                        "label": "Tan Delta Readings",
                        "type": "table",
                        "columns": [
                            {"key": "details", "label": "Details", "type": "text"},
                            {"key": "freq_hz", "label": "f (Hz)", "type": "number"},
                            {"key": "voltage_kv", "label": "U (kV)", "type": "number"},
                            {"key": "current_ma", "label": "I (mA)", "type": "number"},
                            {"key": "cap_pf", "label": "C (pF)", "type": "number"},
                            {"key": "tandelta_pct", "label": "%TanD", "type": "number"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "tandelta_pct",
                                        "thresholds": {
                                            "NCT % Tan Delta (IEC)": {
                                                "Good": [None, 0.5],
                                                "Fair": [0.5,  1.0],
                                                "Poor": [1.0,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                    }
                ]
            },
        ]
    },

    # ════════════════════════════════════════════════════════════
    # CATEGORY-LEVEL TEMPLATES  (SEACMS-AI SRS v1.3)
    # Mapped by request_category, not test_type_id.
    # Field types used:
    #   checkbox  – Yes/No checklist items (SRS 4.1.1)
    #   dropdown  – Pass/Fail, enumerations, severity
    #   number    – Measurements with unit and range
    #   textarea  – Free-text observations
    #   text      – Short string entries
    #   date      – Calendar date picker
    # ════════════════════════════════════════════════════════════

    # ── Preventive Maintenance (SRS §4.1.1 + §4.2.2) ────────────
    "transformer_maintenance": {
        "key": "transformer_maintenance",
        "name": "Transformer Preventive Maintenance",
        "equipment_type": "Power Transformer",
        "description": "Routine / preventive maintenance checklist and major maintenance record for power transformers. Per SRS §4.1.1 and §4.2.2.",
        "supports_multi_session": True,
        "typical_session_interval_days": 180,
        "typical_total_sessions": 2,
        "context_bindings": {"manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number", "rated_mva": "nameplate.rated_mva", "voltage_class": "equipment.voltage_class", "vector_group": "equipment.vector_group"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                {"key": "rated_mva", "label": "Rated MVA", "type": "readonly"},
                {"key": "voltage_class", "label": "Voltage Class", "type": "readonly"},
                {"key": "vector_group", "label": "Vector Group", "type": "readonly"},
                ],
            },
            # ── SRS §5.2.1: Universal metadata mandatory on every maintenance record ──
            {
                "title": "Test / Maintenance Metadata",
                "fields": [
                    {"key": "maintenance_date",      "label": "Date of Maintenance",                  "type": "date",   "required": True},
                    {"key": "maintenance_time",      "label": "Time",                                  "type": "text",   "required": True,  "placeholder": "HH:MM"},
                    {"key": "ambient_temp_c",        "label": "Ambient Temperature",                   "type": "number", "required": True,  "unit": "deg C"},
                    {"key": "humidity_pct",          "label": "Relative Humidity",                     "type": "number", "required": True,  "unit": "%"},
                    {"key": "maintenance_officer",   "label": "Name and Designation of Officer",       "type": "text",   "required": True},
                    {"key": "witness_officer",       "label": "Name of Witnessing Officer",             "type": "text",   "required": False},
                    {"key": "instrument_make",       "label": "Instrument Make",                       "type": "text",   "required": False},
                    {"key": "instrument_model",      "label": "Instrument Model / Serial No.",          "type": "text",   "required": False},
                    {"key": "instrument_calib_date", "label": "Instrument Calibration Validity Date",  "type": "date",   "required": False},
                ],
            },
            # ── SRS §4.1.1: Routine Preventive Maintenance Checklist (Yes/No) ──
            {
                "title": "Routine Maintenance Checklist (SRS §4.1.1)",
                "fields": [
                    {"key": "permit_to_work_obtained",    "label": "Permit to Work obtained",                              "type": "checkbox", "required": True},
                    {"key": "lockout_tagout_applied",      "label": "Lockout / Tagout applied",                             "type": "checkbox", "required": True},
                    {"key": "earth_connections_applied",   "label": "Earth connections applied before commencing work",     "type": "checkbox", "required": True},
                    {"key": "general_cleaning_done",       "label": "General cleaning and housekeeping completed",          "type": "checkbox", "required": True},
                    {"key": "lubrication_done",            "label": "Lubrication of mechanical moving parts done",          "type": "checkbox", "required": True},
                    {"key": "open_close_trip_check",       "label": "Operational check – open / close / trip operations",   "type": "dropdown", "required": True,  "options": ["Pass", "Fail", "N/A"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFNA}},
                    {"key": "alignment_check",             "label": "Alignment checks (isolators, CB mechanism)",           "type": "dropdown", "required": False, "options": ["Pass", "Fail", "N/A"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFNA}},
                    {"key": "indicators_lamps_ok",         "label": "Local / remote indicators and status lamps healthy",   "type": "checkbox", "required": True},
                    {"key": "annunciation_panel_ok",       "label": "Annunciation panel – all alarms healthy",              "type": "checkbox", "required": True},
                    {"key": "pressure_gauges_ok",          "label": "Pressure gauges reading normal",                       "type": "checkbox", "required": True},
                    {"key": "oil_level_indicators_ok",     "label": "Oil level indicators reading normal",                  "type": "checkbox", "required": True},
                    {"key": "temp_indicators_ok",          "label": "Temperature indicators functional and reading normal",  "type": "checkbox", "required": True},
                    {"key": "no_oil_leaks",                "label": "Physical inspection – no oil leaks observed",          "type": "checkbox", "required": True},
                    {"key": "no_cracks_corrosion",         "label": "Physical inspection – no cracks or corrosion",         "type": "checkbox", "required": True},
                    {"key": "no_bird_nesting",             "label": "Physical inspection – no bird nesting",                "type": "checkbox", "required": True},
                    {"key": "earthing_connections_ok",     "label": "Earthing connections intact and tight",                "type": "checkbox", "required": True},
                    {"key": "routine_check_observations",  "label": "Observations during routine checks (free text)",       "type": "textarea", "required": False},
                ],
            },
            # ── SRS §4.2.2: Oil Sampling and Analysis (Power Transformer Major Maintenance) ──
            {
                "title": "Oil Sampling & Analysis (SRS §4.2.2)",
                "fields": [
                    {"key": "oil_sample_collected",      "label": "Oil sample collected",               "type": "checkbox", "required": True},
                    {"key": "bdv_before_kv",             "label": "BDV Before Filtration",              "type": "number",   "required": True,  "unit": "kV"},
                    {"key": "bdv_after_kv",              "label": "BDV After Filtration",               "type": "number",   "required": False, "unit": "kV"},
                    {"key": "acidity_mg_koh_g",          "label": "Acidity (Neutralisation Value)",     "type": "number",   "required": True,  "unit": "mg KOH/g"},
                    {"key": "moisture_ppm",              "label": "Moisture Content",                   "type": "number",   "required": True,  "unit": "ppm"},
                    {"key": "tan_delta_90c",             "label": "Tan Delta at 90 deg C",              "type": "number",   "required": False},
                    {"key": "interfacial_tension_mn_m",  "label": "Interfacial Tension",                "type": "number",   "required": False, "unit": "mN/m"},
                    {"key": "flash_point_c",             "label": "Flash Point",                        "type": "number",   "required": False, "unit": "deg C"},
                    {"key": "oil_filtration_done",       "label": "Oil filtration / reconditioned done","type": "checkbox", "required": False},
                    {"key": "oil_filtration_volume_l",   "label": "Volume Filtered",                    "type": "number",   "required": False, "unit": "litres"},
                    {"key": "oil_replacement_done",      "label": "Full oil replacement done",          "type": "checkbox", "required": False},
                    {"key": "oil_replaced_volume_l",     "label": "Volume of Oil Replaced",             "type": "number",   "required": False, "unit": "litres"},
                    {"key": "oil_grade",                 "label": "Oil Grade",                          "type": "text",     "required": False},
                    {"key": "oil_supplier",              "label": "Oil Supplier",                       "type": "text",     "required": False},
                    {"key": "dga_performed",             "label": "DGA (Dissolved Gas Analysis) performed", "type": "checkbox", "required": False},
                    {"key": "dga_result_before",         "label": "DGA Result Before Maintenance",      "type": "textarea", "required": False},
                    {"key": "dga_result_after",          "label": "DGA Result After Maintenance",       "type": "textarea", "required": False},
                ],
            },
            # ── SRS §4.2.2: OLTC Overhaul ──
            {
                "title": "OLTC / Tap Changer (SRS §4.2.2)",
                "fields": [
                    {"key": "oltc_overhaul_done",        "label": "OLTC overhaul performed",                    "type": "checkbox", "required": False},
                    {"key": "oltc_count_at_overhaul",    "label": "Cumulative OLTC operations at overhaul",     "type": "number",   "required": False},
                    {"key": "oltc_overhaul_scope",       "label": "Scope of OLTC overhaul",                     "type": "textarea", "required": False},
                    {"key": "oltc_parts_replaced",       "label": "Parts replaced during OLTC overhaul",        "type": "textarea", "required": False},
                    {"key": "oltc_test_result_before",   "label": "OLTC test result before overhaul",           "type": "dropdown", "required": False, "options": ["Pass", "Fail", "Not Tested"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFNT}},
                    {"key": "oltc_test_result_after",    "label": "OLTC test result after overhaul",            "type": "dropdown", "required": False, "options": ["Pass", "Fail", "Not Tested"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFNT}},
                    {"key": "active_part_drying_done",   "label": "Active part drying performed",               "type": "checkbox", "required": False},
                    {"key": "drying_method",             "label": "Drying Method",                              "type": "dropdown", "required": False, "options": ["Vapour Phase Drying", "Hot Air Circulation", "Oven Drying", "Other"]},
                    {"key": "drying_duration_hrs",       "label": "Drying Duration",                            "type": "number",   "required": False, "unit": "hours"},
                    {"key": "moisture_before_drying_ppm","label": "Moisture Content Before Drying",             "type": "number",   "required": False, "unit": "ppm"},
                    {"key": "moisture_after_drying_ppm", "label": "Moisture Content After Drying",              "type": "number",   "required": False, "unit": "ppm"},
                ],
            },
            # ── SRS §4.2.2: Gasket / Bushing Replacement ──
            {
                "title": "Gasket & Bushing Replacement (SRS §4.2.2)",
                "fields": [
                    {"key": "gasket_replacement_done",   "label": "Gasket replacement performed",                      "type": "checkbox", "required": False},
                    {"key": "gasket_location",           "label": "Gasket Location (where replaced)",                  "type": "text",     "required": False},
                    {"key": "gaskets_replaced_count",    "label": "Number of Gaskets Replaced",                        "type": "number",   "required": False},
                    {"key": "oil_leakage_before",        "label": "Oil leakage observation before replacement",        "type": "textarea", "required": False},
                    {"key": "oil_leakage_after",         "label": "Oil leakage observation after replacement",         "type": "textarea", "required": False},
                    {"key": "bushing_replacement_done",  "label": "Bushing replacement performed",                     "type": "checkbox", "required": False},
                    {"key": "old_bushing_details",       "label": "Old Bushing Details (make, rating, condition)",      "type": "textarea", "required": False},
                    {"key": "new_bushing_details",       "label": "New Bushing Details (make, rating, serial)",        "type": "textarea", "required": False},
                    {"key": "bushing_replacement_reason","label": "Reason for Bushing Replacement",                    "type": "textarea", "required": False},
                    {"key": "bushing_test_results",      "label": "Bushing Test Results after Replacement",            "type": "textarea", "required": False},
                ],
            },
            # ── SRS §4.1.2: Electrical Tests (IR, PI) ──
            {
                "title": "Electrical Tests",
                "fields": [
                    {"key": "ir_hv_to_earth_mohm",       "label": "IR — HV to Earth",                "type": "number",   "required": True,  "unit": "MOhm"},
                    {"key": "ir_lv_to_earth_mohm",       "label": "IR — LV to Earth",                "type": "number",   "required": True,  "unit": "MOhm"},
                    {"key": "ir_hv_to_lv_mohm",          "label": "IR — HV to LV",                   "type": "number",   "required": False, "unit": "MOhm"},
                    {"key": "pi_ratio",                  "label": "Polarisation Index (PI)",          "type": "number",   "required": False},
                    {"key": "winding_resistance_hv_ohm", "label": "Winding Resistance — HV Phase",   "type": "number",   "required": False, "unit": "Ohm"},
                    {"key": "winding_resistance_lv_ohm", "label": "Winding Resistance — LV Phase",   "type": "number",   "required": False, "unit": "Ohm"},
                    {"key": "ir_test_result",            "label": "IR Test Overall Result",           "type": "dropdown", "required": False, "options": ["Normal", "Alert", "Critical / Abnormal"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_NAC}},
                ],
            },
            # ── SRS §4.1.1: Post-Maintenance Verification ──
            {
                "title": "Post-Maintenance Verification & Sign-off",
                "fields": [
                    {"key": "earthing_restored",         "label": "Earthing connections restored",              "type": "checkbox", "required": True},
                    {"key": "covers_secured",            "label": "All covers, manholes and gaskets secured",   "type": "checkbox", "required": True},
                    {"key": "protection_restored",       "label": "Protection relays restored to service",      "type": "checkbox", "required": True},
                    {"key": "ptw_closed",                "label": "Permit to Work closed",                      "type": "checkbox", "required": True},
                    {"key": "next_maintenance_due",      "label": "Next Maintenance Due Date",                  "type": "date",     "required": False},
                    {"key": "ad_hoc_maintenance_desc",   "label": "Any other ad-hoc maintenance (description)", "type": "textarea", "required": False},
                    {"key": "post_maintenance_status",   "label": "Post-Maintenance Overall Status",            "type": "dropdown", "required": True, "options": ["All Healthy", "Punch Points Pending", "Deficiency — Action Required"], "dropdown_evaluation": {"enabled": True, "value_severities": {"All Healthy": "NORMAL", "Punch Points Pending": "ALERT", "Deficiency — Action Required": "CRITICAL"}}},
                    {"key": "punch_points",              "label": "Open Punch Points (with target closure date)","type": "textarea", "required": False},
                    {"key": "responsible_officer",       "label": "Responsible Officer Sign-off",               "type": "text",     "required": True},
                ],
            },
        ],
    },

    # ── Annual Substation / Equipment Inspection (SRS §6.1) ──────
    "transformer_inspection": {
        "key": "transformer_inspection",
        "name": "Transformer Annual Inspection",
        "equipment_type": "Power Transformer",
        "description": "Annual substation inspection observations and compliance record per SRS §6.1 (TA&QC Module). Captures observation category, severity, compliance and closure status.",
        "supports_multi_session": True,
        "typical_session_interval_days": 365,
        "typical_total_sessions": 1,
        "context_bindings": {"manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number", "voltage_class": "equipment.voltage_class"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                {"key": "voltage_class", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            # ── SRS §5.2.1: Universal metadata ──
            {
                "title": "Inspection Metadata",
                "fields": [
                    {"key": "inspection_date",           "label": "Date of Inspection",                        "type": "date",   "required": True},
                    {"key": "inspection_time",           "label": "Time",                                       "type": "text",   "required": True,  "placeholder": "HH:MM"},
                    {"key": "ambient_temp_c",            "label": "Ambient Temperature",                        "type": "number", "required": True,  "unit": "deg C"},
                    {"key": "humidity_pct",              "label": "Relative Humidity",                          "type": "number", "required": True,  "unit": "%"},
                    {"key": "inspecting_officer",        "label": "Name and Designation of Inspecting Officer", "type": "text",   "required": True},
                    {"key": "witnessing_officer",        "label": "Name of Witnessing Officer",                 "type": "text",   "required": False},
                    {"key": "inspection_type",           "label": "Inspection Type",                            "type": "dropdown", "required": True, "options": ["Annual", "Periodic", "Routine", "Pre-Energisation", "Post-Fault / Emergency", "TA&QC Audit"]},
                    {"key": "equipment_in_service",      "label": "Equipment in service during inspection",     "type": "checkbox", "required": True},
                    {"key": "load_pct",                  "label": "Load at Time of Inspection",                 "type": "number", "required": False, "unit": "%"},
                    {"key": "weather_condition",         "label": "Weather Condition",                          "type": "dropdown", "required": False, "options": ["Clear", "Cloudy", "Raining", "Foggy", "Humid"]},
                ],
            },
            # ── SRS §6.1: Observation Category and Severity ──
            {
                "title": "Inspection Observation (SRS §6.1)",
                "fields": [
                    {"key": "observation_category",      "label": "Observation Category",              "type": "dropdown", "required": True, "options": ["Electrical Safety", "Civil", "Fire Safety", "Documentation", "Environmental", "General Maintenance"]},
                    {"key": "observation_description",   "label": "Detailed Observation Description",  "type": "textarea", "required": True},
                    {"key": "severity",                  "label": "Severity",                          "type": "dropdown", "required": True, "options": ["Major", "Minor", "Advisory"]},
                    {"key": "target_compliance_date",    "label": "Target Compliance Date",            "type": "date",     "required": True},
                    {"key": "photograph_note",           "label": "Photograph Reference / Note",       "type": "textarea", "required": False},
                ],
            },
            # ── SRS §6.1: Visual Inspection Checklist (all Yes/No) ──
            {
                "title": "Visual Inspection Checklist",
                "fields": [
                    # Tank and external condition
                    {"key": "no_oil_leakage",            "label": "No oil leakage from tank / gaskets / fittings",      "type": "checkbox", "required": True},
                    {"key": "no_bushing_damage",          "label": "Bushings — no cracks, chips or flashover marks",     "type": "checkbox", "required": True},
                    {"key": "tank_paint_ok",              "label": "Tank paint in good condition (no severe corrosion)", "type": "checkbox", "required": True},
                    {"key": "conservator_level_ok",       "label": "Conservator oil level in normal range",              "type": "checkbox", "required": True},
                    {"key": "silica_gel_ok",              "label": "Silica gel breather — blue / active",                "type": "checkbox", "required": True},
                    {"key": "pressure_relief_intact",     "label": "Pressure relief device intact and not operated",     "type": "checkbox", "required": True},
                    {"key": "nameplate_legible",          "label": "Nameplate legible and intact",                       "type": "checkbox", "required": True},
                    {"key": "marshalling_box_ok",         "label": "Marshalling box — clean, dry, no pests / moisture",  "type": "checkbox", "required": True},
                    {"key": "no_bird_nesting",            "label": "No bird nesting on equipment or structure",          "type": "checkbox", "required": True},
                    # Earthing
                    {"key": "earthing_straps_ok",         "label": "Earthing straps intact and connected",               "type": "checkbox", "required": True},
                    {"key": "neutral_earthing_ok",        "label": "Neutral earthing arrangement intact",                "type": "checkbox", "required": True},
                    # Cooling
                    {"key": "radiators_clean",            "label": "Radiators clean — no blockage or sludge",            "type": "checkbox", "required": True},
                    {"key": "cooling_fans_running",       "label": "Cooling fans running without vibration / noise",     "type": "checkbox", "required": True},
                    {"key": "oil_temp_indicator_ok",      "label": "Oil temperature indicator functional — no alarm",    "type": "checkbox", "required": True},
                    {"key": "winding_temp_indicator_ok",  "label": "Winding temperature indicator — no alarm",           "type": "checkbox", "required": True},
                    {"key": "oil_temp_reading_c",         "label": "Oil Temperature reading",                            "type": "number",   "required": False, "unit": "deg C"},
                    {"key": "winding_temp_reading_c",     "label": "Winding Temperature reading",                        "type": "number",   "required": False, "unit": "deg C"},
                    # OLTC
                    {"key": "tap_changer_type",           "label": "Tap Changer Type",                                   "type": "dropdown", "required": False, "options": ["OLTC (Motor-operated)", "DETC (Off-Load)", "N/A"]},
                    {"key": "tap_position",               "label": "Current Tap Position",                                "type": "text",     "required": False},
                    {"key": "tap_changer_ok",             "label": "Tap changer operation smooth (no hunting)",           "type": "checkbox", "required": False},
                    {"key": "oltc_counter_reading",       "label": "OLTC Operation Counter Reading",                     "type": "text",     "required": False},
                    # Protection
                    {"key": "buchholz_relay_ok",          "label": "Buchholz relay — no gas / oil accumulation",         "type": "checkbox", "required": True},
                    {"key": "sudden_pressure_relay_ok",   "label": "Sudden pressure relay intact and healthy",           "type": "checkbox", "required": True},
                    {"key": "differential_relay_ok",      "label": "Differential relay healthy (no alarm)",              "type": "checkbox", "required": False},
                    {"key": "active_alarms_present",      "label": "Active alarms on panel / SCADA (note if Yes)",       "type": "checkbox", "required": True},
                    {"key": "alarm_details",              "label": "Alarm Details (if any active alarms)",                "type": "textarea", "required": False},
                ],
            },
            # ── SRS §6.1: Compliance Record (filled by substation staff) ──
            {
                "title": "Compliance & Closure (SRS §6.1)",
                "fields": [
                    {"key": "action_taken_description",  "label": "Action Taken Description",                "type": "textarea", "required": False},
                    {"key": "date_of_compliance",        "label": "Date of Compliance",                      "type": "date",     "required": False},
                    {"key": "compliance_status",         "label": "Observation Status",                      "type": "dropdown", "required": True, "options": ["Open", "Closed", "Reopened", "Accepted with Remarks"]},
                    {"key": "reopen_remarks",            "label": "Remarks on Reopen (if status = Reopened)","type": "textarea", "required": False},
                    {"key": "outcome",                   "label": "Inspection Outcome",                      "type": "dropdown", "required": True, "options": ["Accepted", "Accepted with Remarks", "Rejected"]},
                    {"key": "responsible_officer",       "label": "Responsible Officer",                     "type": "text",     "required": True},
                ],
            },
        ],
    },

    # ── Power Transformer Repair Lifecycle — 10 Stages (SRS §7) ──
    "transformer_repair_lifecycle": {
        "key": "transformer_repair_lifecycle",
        "name": "Transformer Repair Lifecycle (10-Stage Tracking)",
        "equipment_type": "Power Transformer",
        "description": "Ten-stage repair lifecycle tracking per SRS §7.1. Each stage records date, document reference, responsible officer, and any contractual delay. Post-commissioning surveillance data also captured.",
        "supports_multi_session": True,
        "typical_session_interval_days": 14,
        "typical_total_sessions": 10,
        "sections": [
            # ── SRS §7.1 Stage 1 ──
            {
                "title": "Stage 1 — Failure Report (SRS §7.1)",
                "fields": [
                    {"key": "s1_failure_date",           "label": "Date of Failure / Outage",         "type": "date",     "required": True},
                    {"key": "s1_failure_mode",           "label": "Mode of Failure",                  "type": "dropdown", "required": True, "options": ["Internal Fault — Winding", "Internal Fault — Core", "Bushing Failure", "Oil Contamination / Degradation", "Tap Changer Failure", "External Fault (Lightning / Short Circuit)", "Overloading / Thermal", "Ageing", "Other"]},
                    {"key": "s1_failure_brief",          "label": "Brief Report on Failure",          "type": "textarea", "required": True},
                    {"key": "s1_doc_reference",          "label": "Failure Report Document Reference","type": "text",     "required": False},
                    {"key": "s1_responsible_officer",    "label": "Responsible Officer",              "type": "text",     "required": True},
                    {"key": "s1_contractual_date",       "label": "Contracted Completion Date",       "type": "date",     "required": False},
                    {"key": "s1_actual_date",            "label": "Actual Completion Date",           "type": "date",     "required": False},
                    {"key": "s1_delay_reason",           "label": "Delay Reason (if delayed)",        "type": "dropdown", "required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                    {"key": "s1_remarks",                "label": "Remarks",                          "type": "textarea", "required": False},
                ],
            },
            # ── SRS §7.1 Stage 2 ──
            {
                "title": "Stage 2 — Transformer Repair Committee (SRS §7.1)",
                "fields": [
                    {"key": "s2_committee_date",         "label": "Date of Committee Presentation",   "type": "date",     "required": True},
                    {"key": "s2_minutes_reference",      "label": "Minutes of Meeting Reference",     "type": "text",     "required": False},
                    {"key": "s2_committee_decision",     "label": "Committee Decision",               "type": "dropdown", "required": True, "options": ["Repair Approved", "Replacement Recommended", "Further Investigation Required", "Pending"]},
                    {"key": "s2_responsible_officer",    "label": "Responsible Officer",              "type": "text",     "required": True},
                    {"key": "s2_contractual_date",       "label": "Contracted Completion Date",       "type": "date",     "required": False},
                    {"key": "s2_actual_date",            "label": "Actual Completion Date",           "type": "date",     "required": False},
                    {"key": "s2_delay_reason",           "label": "Delay Reason (if delayed)",        "type": "dropdown", "required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                    {"key": "s2_remarks",                "label": "Remarks",                          "type": "textarea", "required": False},
                ],
            },
            # ── SRS §7.1 Stage 3 ──
            {
                "title": "Stage 3 — Allotment to Repairer (SRS §7.1)",
                "fields": [
                    {"key": "s3_allotment_date",         "label": "Date of Allotment",                "type": "date",     "required": True},
                    {"key": "s3_repairer_name",          "label": "Name of Repairer / Workshop",      "type": "text",     "required": True},
                    {"key": "s3_communication_ref",      "label": "Communication Reference (CEE RT&R&D / CEE Transmission Zone)", "type": "text", "required": False},
                    {"key": "s3_work_order_no",          "label": "Work Order / PO Number",           "type": "text",     "required": False},
                    {"key": "s3_responsible_officer",    "label": "Responsible Officer",              "type": "text",     "required": True},
                    {"key": "s3_contractual_date",       "label": "Contracted Completion Date",       "type": "date",     "required": False},
                    {"key": "s3_actual_date",            "label": "Actual Completion Date",           "type": "date",     "required": False},
                    {"key": "s3_delay_reason",           "label": "Delay Reason (if delayed)",        "type": "dropdown", "required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                    {"key": "s3_remarks",                "label": "Remarks",                          "type": "textarea", "required": False},
                ],
            },
            # ── SRS §7.1 Stage 4 ──
            {
                "title": "Stage 4 — Lifting by Repairer (SRS §7.1)",
                "fields": [
                    {"key": "s4_lifting_date",           "label": "Date of Lifting / Dispatch from Substation", "type": "date", "required": True},
                    {"key": "s4_vehicle_details",        "label": "Vehicle Details (type, registration)", "type": "text",   "required": True},
                    {"key": "s4_driver_name",            "label": "Driver Name",                         "type": "text",   "required": True},
                    {"key": "s4_dispatch_doc_ref",       "label": "Dispatch Document Reference",         "type": "text",   "required": False},
                    {"key": "s4_insurance_doc_ref",      "label": "Transit Insurance Document Reference","type": "text",   "required": False},
                    {"key": "s4_responsible_officer",    "label": "Responsible Officer",                 "type": "text",   "required": True},
                    {"key": "s4_contractual_date",       "label": "Contracted Completion Date",          "type": "date",   "required": False},
                    {"key": "s4_actual_date",            "label": "Actual Completion Date",              "type": "date",   "required": False},
                    {"key": "s4_delay_reason",           "label": "Delay Reason (if delayed)",           "type": "dropdown","required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                    {"key": "s4_remarks",                "label": "Remarks",                             "type": "textarea","required": False},
                ],
            },
            # ── SRS §7.1 Stage 5 ──
            {
                "title": "Stage 5 — Joint Inspection at Vendor Works (SRS §7.1)",
                "fields": [
                    {"key": "s5_inspection_date",        "label": "Date of Joint Inspection",            "type": "date",   "required": True},
                    {"key": "s5_inspection_report_ref",  "label": "Inspection Report Reference",         "type": "text",   "required": False},
                    {"key": "s5_inspection_outcome",     "label": "Inspection Outcome",                  "type": "dropdown","required": True, "options": ["Satisfactory", "Satisfactory with Observations", "Unsatisfactory — Rework Required"]},
                    {"key": "s5_defects_found",          "label": "Defects / Observations found at Vendor Works", "type": "textarea", "required": False},
                    {"key": "s5_responsible_officer",    "label": "Responsible Officer (KPTCL)",         "type": "text",   "required": True},
                    {"key": "s5_contractual_date",       "label": "Contracted Completion Date",          "type": "date",   "required": False},
                    {"key": "s5_actual_date",            "label": "Actual Completion Date",              "type": "date",   "required": False},
                    {"key": "s5_delay_reason",           "label": "Delay Reason (if delayed)",           "type": "dropdown","required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                    {"key": "s5_remarks",                "label": "Remarks",                             "type": "textarea","required": False},
                ],
            },
            # ── SRS §7.1 Stage 6 ──
            {
                "title": "Stage 6 — Estimate & Revised Work Award (SRS §7.1)",
                "fields": [
                    {"key": "s6_estimate_date",          "label": "Date of Estimate Preparation",        "type": "date",   "required": True},
                    {"key": "s6_estimate_amount",        "label": "Estimated Repair Amount",             "type": "number", "required": False, "unit": "INR"},
                    {"key": "s6_estimate_doc_ref",       "label": "Estimate Document Reference",         "type": "text",   "required": False},
                    {"key": "s6_work_award_date",        "label": "Date of Revised Work Award",          "type": "date",   "required": False},
                    {"key": "s6_award_letter_ref",       "label": "Award Letter Reference",              "type": "text",   "required": False},
                    {"key": "s6_responsible_officer",    "label": "Responsible Officer",                 "type": "text",   "required": True},
                    {"key": "s6_contractual_date",       "label": "Contracted Completion Date",          "type": "date",   "required": False},
                    {"key": "s6_actual_date",            "label": "Actual Completion Date",              "type": "date",   "required": False},
                    {"key": "s6_delay_reason",           "label": "Delay Reason (if delayed)",           "type": "dropdown","required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                    {"key": "s6_remarks",                "label": "Remarks",                             "type": "textarea","required": False},
                ],
            },
            # ── SRS §7.1 Stage 7 ──
            {
                "title": "Stage 7 — Stage Inspections During Repair (SRS §7.1)",
                "fields": [
                    {"key": "s7_stage_insp_1_date",      "label": "Stage Inspection 1 — Date",           "type": "date",   "required": False},
                    {"key": "s7_stage_insp_1_result",    "label": "Stage Inspection 1 — Result",         "type": "dropdown","required": False, "options": ["Pass", "Fail", "Pass with Observations"]},
                    {"key": "s7_stage_insp_2_date",      "label": "Stage Inspection 2 — Date",           "type": "date",   "required": False},
                    {"key": "s7_stage_insp_2_result",    "label": "Stage Inspection 2 — Result",         "type": "dropdown","required": False, "options": ["Pass", "Fail", "Pass with Observations"]},
                    {"key": "s7_stage_insp_3_date",      "label": "Stage Inspection 3 — Date",           "type": "date",   "required": False},
                    {"key": "s7_stage_insp_3_result",    "label": "Stage Inspection 3 — Result",         "type": "dropdown","required": False, "options": ["Pass", "Fail", "Pass with Observations"]},
                    {"key": "s7_stage_observations",     "label": "Observations across Stage Inspections","type": "textarea","required": False},
                    {"key": "s7_responsible_officer",    "label": "Responsible Officer (Stage Inspections)","type": "text", "required": False},
                    {"key": "s7_contractual_date",       "label": "Contracted Completion Date",          "type": "date",   "required": False},
                    {"key": "s7_actual_date",            "label": "Actual Completion Date",              "type": "date",   "required": False},
                    {"key": "s7_delay_reason",           "label": "Delay Reason (if delayed)",           "type": "dropdown","required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                ],
            },
            # ── SRS §7.1 Stage 8 ──
            {
                "title": "Stage 8 — Final Inspection at Vendor Works (SRS §7.1)",
                "fields": [
                    {"key": "s8_final_insp_date",        "label": "Date of Final Inspection",            "type": "date",   "required": True},
                    {"key": "s8_final_insp_report_ref",  "label": "Final Inspection Report Reference",   "type": "text",   "required": False},
                    {"key": "s8_final_insp_outcome",     "label": "Final Inspection Outcome",            "type": "dropdown","required": True, "options": ["Accepted — Cleared for Dispatch", "Accepted with Punch Points", "Rejected — Rework Required"]},
                    {"key": "s8_punch_points",           "label": "Punch Points (if any)",               "type": "textarea","required": False},
                    {"key": "s8_test_results_summary",   "label": "Test Results Summary at Final Inspection", "type": "textarea","required": False},
                    {"key": "s8_responsible_officer",    "label": "Responsible Officer",                 "type": "text",   "required": True},
                    {"key": "s8_contractual_date",       "label": "Contracted Completion Date",          "type": "date",   "required": False},
                    {"key": "s8_actual_date",            "label": "Actual Completion Date",              "type": "date",   "required": False},
                    {"key": "s8_delay_reason",           "label": "Delay Reason (if delayed)",           "type": "dropdown","required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                ],
            },
            # ── SRS §7.1 Stage 9 ──
            {
                "title": "Stage 9 — Dispatch of Transformer (SRS §7.1)",
                "fields": [
                    {"key": "s9_dispatch_date",          "label": "Date of Dispatch from Vendor Works",  "type": "date",   "required": True},
                    {"key": "s9_transport_details",      "label": "Transport Details (vehicle type, registration, driver)", "type": "textarea","required": True},
                    {"key": "s9_insurance_doc_ref",      "label": "Insurance Document Reference",        "type": "text",   "required": False},
                    {"key": "s9_eta_substation",         "label": "Estimated Arrival at Substation",     "type": "date",   "required": False},
                    {"key": "s9_actual_arrival_date",    "label": "Actual Arrival at Substation",        "type": "date",   "required": False},
                    {"key": "s9_transit_damage",         "label": "Any transit damage observed",         "type": "checkbox","required": True},
                    {"key": "s9_transit_damage_details", "label": "Transit Damage Details (if any)",     "type": "textarea","required": False},
                    {"key": "s9_responsible_officer",    "label": "Responsible Officer",                 "type": "text",   "required": True},
                    {"key": "s9_contractual_date",       "label": "Contracted Completion Date",          "type": "date",   "required": False},
                    {"key": "s9_delay_reason",           "label": "Delay Reason (if delayed)",           "type": "dropdown","required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                ],
            },
            # ── SRS §7.1 Stage 10 ──
            {
                "title": "Stage 10 — Erection, Testing & Commissioning (SRS §7.1)",
                "fields": [
                    {"key": "s10_erection_date",         "label": "Date of Erection / Re-installation",  "type": "date",   "required": True},
                    {"key": "s10_commissioning_date",    "label": "Date of Commissioning",               "type": "date",   "required": True},
                    {"key": "s10_commissioning_report_ref","label":"Commissioning Report Reference",      "type": "text",   "required": False},
                    # Post-repair test results (SRS §7.3)
                    {"key": "s10_ir_hv_mohm",            "label": "IR — HV to Earth (Post-Repair)",      "type": "number", "required": True,  "unit": "MOhm"},
                    {"key": "s10_ir_lv_mohm",            "label": "IR — LV to Earth (Post-Repair)",      "type": "number", "required": True,  "unit": "MOhm"},
                    {"key": "s10_bdv_kv",                "label": "Oil BDV (Post-Repair)",               "type": "number", "required": True,  "unit": "kV"},
                    {"key": "s10_turns_ratio_ok",        "label": "Turns ratio within specification",    "type": "dropdown","required": True, "options": ["Pass", "Fail"]},
                    {"key": "s10_winding_resistance_ok", "label": "Winding resistance within specification","type":"dropdown","required": True, "options": ["Pass", "Fail"]},
                    {"key": "s10_no_load_test_ok",       "label": "No-load test result",                 "type": "dropdown","required": True, "options": ["Pass", "Fail"]},
                    {"key": "s10_test_results_summary",  "label": "Complete Test Results Summary",       "type": "textarea","required": True},
                    {"key": "s10_commissioning_status",  "label": "Commissioning Status",                "type": "dropdown","required": True, "options": ["Commissioned — In Service", "Commissioned with Surveillance", "Commissioning Failed — Rework Required"]},
                    {"key": "s10_responsible_officer",   "label": "Responsible Officer",                 "type": "text",   "required": True},
                    {"key": "s10_contractual_date",      "label": "Contracted Completion Date",          "type": "date",   "required": False},
                    {"key": "s10_actual_date",           "label": "Actual Completion Date",              "type": "date",   "required": False},
                    {"key": "s10_delay_reason",          "label": "Delay Reason (if delayed)",           "type": "dropdown","required": False, "options": ["Vendor-attributable", "KPTCL-attributable", "No Delay"]},
                    # SRS §7.2 Delay Accountability
                    {"key": "total_vendor_delay_days",   "label": "Total Vendor-Attributable Delay",     "type": "number", "required": False, "unit": "days"},
                    {"key": "total_kptcl_delay_days",    "label": "Total KPTCL-Attributable Delay",      "type": "number", "required": False, "unit": "days"},
                ],
            },
            # ── SRS §7.3: Post-Commissioning Surveillance ──
            {
                "title": "Post-Commissioning Surveillance (SRS §7.3)",
                "fields": [
                    {"key": "surveillance_period_months","label": "Surveillance Period",                 "type": "number", "required": True,  "unit": "months", "default": "24"},
                    {"key": "surveillance_start_date",   "label": "Surveillance Start Date",             "type": "date",   "required": True},
                    {"key": "surveillance_end_date",     "label": "Surveillance End Date",               "type": "date",   "required": False},
                    {"key": "dga_result_1m",             "label": "DGA at 1 Month Post-Commissioning",  "type": "dropdown","required": False, "options": ["Normal", "Alert", "Critical / Abnormal", "Not Done"]},
                    {"key": "bdv_result_1m",             "label": "BDV at 1 Month Post-Commissioning",  "type": "dropdown","required": False, "options": ["Normal", "Alert", "Critical / Abnormal", "Not Done"]},
                    {"key": "ir_result_6m",              "label": "IR Test at 6 Months",                "type": "dropdown","required": False, "options": ["Normal", "Alert", "Critical / Abnormal", "Not Done"]},
                    {"key": "loading_history_summary",   "label": "Loading History Summary (surveillance period)", "type": "textarea","required": False},
                    {"key": "incidents_during_surveillance","label":"Any incidents during surveillance period","type":"checkbox","required": True},
                    {"key": "incident_details",          "label": "Incident Details (if any)",           "type": "textarea","required": False},
                    {"key": "overall_quality_rating",    "label": "Overall Quality Rating of Repair",    "type": "dropdown","required": True, "options": ["Excellent", "Good", "Satisfactory", "Poor", "Unsatisfactory"]},
                    {"key": "post_repair_evaluation",    "label": "Post-Repair Evaluation Summary",      "type": "textarea","required": True},
                    {"key": "warranty_expiry_date",      "label": "Repair Warranty Expiry Date",         "type": "date",   "required": False},
                ],
            },
        ],
    },

    # ────────────────────────────────────────────────────────────
    # Calibration — Protection Relay
    # enable_calibration=True, DATE_ADD rule
    # ────────────────────────────────────────────────────────────
    "protection_relay_calibration": {
        "key": "protection_relay_calibration",
        "name": "Protection Relay Calibration",
        "equipment_type": "Protection Relay",
        "description": "Calibration record for protection relays — DATE_ADD rule, pre-due scheduling, FAIL → repair trigger.",
        "enable_calibration": True,
        "multi_session": False,
        "sections": [
            {
                "title": "Relay Identification",
                "fields": [
                    {"key": "relay_make",       "label": "Relay Make",         "type": "text",   "required": True},
                    {"key": "relay_model",      "label": "Relay Model / Type", "type": "text",   "required": True},
                    {"key": "relay_serial",     "label": "Serial Number",      "type": "text",   "required": False},
                    {"key": "relay_location",   "label": "Location / Bay",     "type": "text",   "required": False},
                ],
            },
            {
                "title": "Calibration Checks",
                "fields": [
                    {"key": "pickup_current_set",    "label": "Pickup Current (Set)",    "type": "number", "unit": "A",   "required": True},
                    {"key": "pickup_current_actual", "label": "Pickup Current (Actual)", "type": "number", "unit": "A",   "required": True},
                    {"key": "tms_setting",           "label": "TMS Setting",             "type": "number",                "required": True},
                    {"key": "operating_time_2x",     "label": "Operating Time at 2×Is",  "type": "number", "unit": "sec", "required": True},
                    {"key": "operating_time_5x",     "label": "Operating Time at 5×Is",  "type": "number", "unit": "sec", "required": False},
                    {"key": "ef_pickup_set",         "label": "EF Pickup (Set)",         "type": "number", "unit": "A",   "required": False},
                    {"key": "ef_pickup_actual",      "label": "EF Pickup (Actual)",      "type": "number", "unit": "A",   "required": False},
                    {"key": "burden_va",             "label": "Burden",                  "type": "number", "unit": "VA",  "required": False},
                    {"key": "insulation_resistance", "label": "Insulation Resistance",   "type": "number", "unit": "MΩ",  "required": False},
                ],
            },
            {
                "title": "Calibration Record",
                "fields": [
                    {"key": "calibration_date",    "label": "Calibration Date",                  "type": "date",     "required": True},
                    {"key": "validity_months",     "label": "Validity (Months)",                 "type": "number",   "required": True,  "unit": "months"},
                    {"key": "calibrated_by",       "label": "Calibrated By (Agency / Lab)",      "type": "text",     "required": False},
                    {"key": "certificate_number",  "label": "Certificate Number",                "type": "text",     "required": False},
                    {"key": "next_calibration_due","label": "Next Calibration Due (computed)",   "type": "calculated", "formula": "date_add(calibration_date, validity_months)", "required": False, "read_only": True},
                    {"key": "notes",               "label": "Notes / Observations",              "type": "textarea", "required": False},
                ],
            },
        ],
        "rules": [
            {
                "field": "calibration_date",
                "type": "DATE_ADD",
                "config": {
                    "validity_field": "validity_months",
                    "result_field": "recommendation_type",
                    "order_by": "calibration_date",
                    "group_by": "equipment_id",
                    "requires_multi_session": False,
                },
            }
        ],
    },

    # ────────────────────────────────────────────────────────────
    # Calibration — Electronic Tri-vector Meter
    # enable_calibration=True, DATE_ADD rule
    # ────────────────────────────────────────────────────────────
    "tri_vector_meter_calibration": {
        "key": "tri_vector_meter_calibration",
        "name": "Electronic Tri-vector Meter Calibration",
        "equipment_type": "Electronic Tri-vector Meter",
        "description": "Calibration record for electronic tri-vector meters — DATE_ADD rule, pre-due scheduling, FAIL → repair trigger.",
        "enable_calibration": True,
        "multi_session": False,
        "sections": [
            {
                "title": "Meter Identification",
                "fields": [
                    {"key": "meter_make",         "label": "Meter Make",           "type": "text",     "required": True},
                    {"key": "meter_model",        "label": "Meter Model",          "type": "text",     "required": True},
                    {"key": "meter_serial",       "label": "Serial Number",        "type": "text",     "required": True},
                    {"key": "meter_class",        "label": "Accuracy Class",       "type": "dropdown", "required": True, "options": ["Class 0.2S", "Class 0.5S", "Class 1", "Class 2"]},
                    {"key": "ct_ratio",           "label": "CT Ratio",             "type": "text",     "required": True},
                    {"key": "pt_ratio",           "label": "PT Ratio",             "type": "text",     "required": True},
                    {"key": "meter_location",     "label": "Location / Feeder",    "type": "text",     "required": False},
                ],
            },
            {
                "title": "Calibration Measurements",
                "fields": [
                    {"key": "kWh_error_pct",      "label": "kWh Error (%)",             "type": "number", "unit": "%",   "required": True},
                    {"key": "kVAh_error_pct",     "label": "kVAh Error (%)",            "type": "number", "unit": "%",   "required": True},
                    {"key": "kVARh_error_pct",    "label": "kVARh Error (%)",           "type": "number", "unit": "%",   "required": True},
                    {"key": "voltage_error_pct",  "label": "Voltage Measurement Error", "type": "number", "unit": "%",   "required": False},
                    {"key": "current_error_pct",  "label": "Current Measurement Error", "type": "number", "unit": "%",   "required": False},
                    {"key": "phase_angle_error",  "label": "Phase Angle Error",         "type": "number", "unit": "min", "required": False},
                    {"key": "burden_va",          "label": "Voltage Circuit Burden",    "type": "number", "unit": "VA",  "required": False},
                    {"key": "meter_constant",     "label": "Meter Constant",            "type": "number", "unit": "imp/kWh", "required": False},
                    {"key": "test_current_amps",  "label": "Test Current",              "type": "number", "unit": "A",   "required": False},
                    {"key": "test_voltage_v",     "label": "Test Voltage",              "type": "number", "unit": "V",   "required": False},
                ],
            },
            {
                "title": "Calibration Record",
                "fields": [
                    {"key": "calibration_date",   "label": "Calibration Date",                 "type": "date",     "required": True},
                    {"key": "validity_months",    "label": "Validity (Months)",                "type": "number",   "required": True,  "unit": "months"},
                    {"key": "calibrated_by",      "label": "Calibrated By (Agency / Lab)",     "type": "text",     "required": False},
                    {"key": "certificate_number", "label": "Certificate Number",               "type": "text",     "required": False},
                    {"key": "next_calibration_due","label": "Next Calibration Due (computed)", "type": "calculated", "formula": "date_add(calibration_date, validity_months)", "required": False, "read_only": True},
                    {"key": "notes",              "label": "Notes / Observations",             "type": "textarea", "required": False},
                ],
            },
        ],
        "rules": [
            {
                "field": "calibration_date",
                "type": "DATE_ADD",
                "config": {
                    "validity_field": "validity_months",
                    "result_field": "recommendation_type",
                    "order_by": "calibration_date",
                    "group_by": "equipment_id",
                    "requires_multi_session": False,
                },
            }
        ],
    },

    # ────────────────────────────────────────────────────────────
    # Cumulative — Circuit Breaker Operations Count
    # enable_cumulative=True, CUMULATIVE_DIFF rule
    # ────────────────────────────────────────────────────────────
    "circuit_breaker_operations": {
        "key": "circuit_breaker_operations",
        "name": "Circuit Breaker Operations Count",
        "equipment_type": "Circuit Breaker",
        "description": "Multi-session cumulative operations count for circuit breakers — triggers overhaul when threshold crossed.",
        "enable_cumulative": True,
        "multi_session": True,
        "sections": [
            {
                "title": "Circuit Breaker Identification",
                "fields": [
                    {"key": "breaker_make",       "label": "Breaker Make",         "type": "text",     "required": True},
                    {"key": "breaker_type",       "label": "Breaker Type",         "type": "dropdown", "required": True, "options": ["SF6", "Vacuum", "Air Blast", "Oil", "Other"]},
                    {"key": "breaker_serial",     "label": "Serial Number",        "type": "text",     "required": False},
                    {"key": "breaker_voltage_kv", "label": "Rated Voltage",        "type": "number",   "required": True, "unit": "kV"},
                    {"key": "breaker_location",   "label": "Location / Bay",       "type": "text",     "required": False},
                ],
            },
            {
                "title": "Operations Reading",
                "fields": [
                    {"key": "reading",       "label": "Operations Counter Reading", "type": "number", "required": True,  "unit": "ops"},
                    {"key": "reading_date",  "label": "Reading Date",              "type": "date",   "required": True},
                    {"key": "reading_by",    "label": "Recorded By",               "type": "text",   "required": False},
                    {"key": "notes",         "label": "Notes / Observations",      "type": "textarea","required": False},
                ],
            },
        ],
        "rules": [
            {
                "field": "reading",
                "type": "CUMULATIVE_DIFF",
                "config": {
                    "order_by": "reading_date",
                    "group_by": "equipment_id",
                    "requires_multi_session": True,
                    "reset_on_drop": True,
                    # Default overhaul threshold — overridable per equipment via EquipmentOverhaulConfig
                    "default_threshold": 2000,  # ops — typical CB overhaul threshold
                },
            }
        ],
    },

    # ────────────────────────────────────────────────────────────
    # Cumulative — OLTC Operations Count
    # enable_cumulative=True, CUMULATIVE_DIFF rule
    # ────────────────────────────────────────────────────────────
    "oltc_operations": {
        "key": "oltc_operations",
        "name": "OLTC Operations Count",
        "equipment_type": "Power Transformer",
        "description": "Multi-session cumulative tap-change operations count for OLTCs — triggers overhaul when threshold crossed.",
        "enable_cumulative": True,
        "multi_session": True,
        "sections": [
            {
                "title": "OLTC Identification",
                "fields": [
                    {"key": "oltc_make",          "label": "OLTC Make",            "type": "text",     "required": True},
                    {"key": "oltc_type",          "label": "OLTC Type",            "type": "dropdown", "required": True, "options": ["Motor-operated OLTC", "Pneumatic OLTC", "Other"]},
                    {"key": "oltc_serial",        "label": "Serial Number",        "type": "text",     "required": False},
                    {"key": "transformer_rating", "label": "Associated Transformer Rating", "type": "text", "required": False},
                    {"key": "oltc_location",      "label": "Location / Substation","type": "text",     "required": False},
                ],
            },
            {
                "title": "Operations Reading",
                "fields": [
                    {"key": "reading",       "label": "Tap-Change Counter Reading", "type": "number", "required": True,  "unit": "ops"},
                    {"key": "reading_date",  "label": "Reading Date",               "type": "date",   "required": True},
                    {"key": "reading_by",    "label": "Recorded By",                "type": "text",   "required": False},
                    {"key": "notes",         "label": "Notes / Observations",       "type": "textarea","required": False},
                ],
            },
        ],
        "rules": [
            {
                "field": "reading",
                "type": "CUMULATIVE_DIFF",
                "config": {
                    "order_by": "reading_date",
                    "group_by": "equipment_id",
                    "requires_multi_session": True,
                    "reset_on_drop": True,
                    # Default overhaul threshold — overridable per equipment via EquipmentOverhaulConfig
                    "default_threshold": 5000,  # ops — typical OLTC overhaul threshold
                },
            }
        ],
    },
    # ────────────────────────────────────────────────────────────────────────────
    # Transformer Insulating Oil Sample Test  (IS 1866:2017)
    #
    # transformer_voltage is pre-populated from the equipment record (e.g. "220kV").
    # No intermediate calculated field is needed — the THRESHOLD lookup_field carries
    # an inline LOOKUP that maps the raw voltage to an IS 1866 class on the fly:
    #   "11kV"/"33kV"/"66kV"         → "<=72.5kV"
    #   "66kV"/"110kV"/"132kV"       → "72.5-170kV"
    #   "220kV"/"400kV"              → ">170kV"
    #
    # Test results are a fixed table (one row per IS 1866 parameter).
    # The THRESHOLD rule navigates thresholds[test_name][voltage_class] and
    # range-matches the measured value. All limit data lives in the rule config.
    # overall_condition aggregates oil_test_results.condition via AGGREGATE_STATUS.
    # ────────────────────────────────────────────────────────────────────────────
    "transformer_oil_test": {
    "key": "transformer_oil_test",
    "name": "Transformer Oil Test",
    "equipment_type": "Power Transformer",
    "description": "Insulating oil sample analysis as per IS 1866:2017.",
    "supports_multi_session": False,
    "typical_session_interval_days": 365,
    "typical_total_sessions": 1,
    "context_bindings": {
        "sub_station":         "equipment.department_name",
        "make":                "equipment.manufacturer",
        "serial_number":       "equipment.factory_serial_number",
        "capacity_mva":        "nameplate.rated_mva",
        "year_of_manufacture": "equipment.year_of_manufacture",
        "vector_group":        "equipment.vector_group",
        "transformer_voltage": "equipment.voltage_class",
    },
    "sections": [
        # ── Equipment Details (auto-filled) ──────────────────────────────
        {
            "title": "Equipment Details",
            "collapsed": True,
            "fields": [
                {"key": "sub_station",          "label": "Sub Station",         "type": "readonly"},
                {"key": "make",                "label": "Manufacturer",        "type": "readonly"},
                {"key": "serial_number",        "label": "Serial Number",       "type": "readonly"},
                {"key": "capacity_mva",         "label": "Rated MVA",           "type": "readonly"},
                {"key": "year_of_manufacture",  "label": "Year of Manufacture", "type": "readonly"},
                {"key": "vector_group",         "label": "Vector Group",        "type": "readonly"},
                {"key": "transformer_voltage",  "label": "Voltage Class (kV)",  "type": "readonly"},
            ],
        },

        # ── Oil Test Results ─────────────────────────────────────────────
        {
            "title": "Oil Test Measurements",
            "fields": [
            {
                "key": "oil_test_results",
                "label": "Test Results as per IS 1866:2017",
                "type": "table",
                "allow_add_rows": False,
                "allow_delete_rows": False,
                "lock_default_rows": False,
                "columns": [
                    {"key": "test_name",      "label": "Parameter",       "type": "readonly"},
                    {"key": "unit",           "label": "Unit",            "type": "readonly"},
                    {"key": "measured_value", "label": "Measured Value",  "type": "number"},
                    {
                        "key": "condition",
                        "label": "Condition",
                        "type": "calculated",
                        "rule": {
                            "type": "THRESHOLD",
                            "config": {
                                "input_field": "measured_value",
                                "lookup_fields": [
                                    "test_name",
                                    {
                                        "field": "$form.transformer_voltage",
                                        "mapping": {
                                            "11":  "<=72.5kV",
                                            "33":  "<=72.5kV",
                                            "66":  "<=72.5kV",
                                            "110": "72.5-170kV",
                                            "132": "72.5-170kV",
                                            "220": ">170kV",
                                            "400": ">170kV",
                                        },
                                    },
                                ],
                                "thresholds": {
                                    "Acidity": {
                                        ">170kV":     {"Good": [0, 0.10], "Fair": [0.10, 0.15], "Poor": [0.15, None]},
                                        "72.5-170kV": {"Good": [0, 0.10], "Fair": [0.10, 0.20], "Poor": [0.20, None]},
                                        "<=72.5kV":   {"Good": [0, 0.15], "Fair": [0.15, 0.30], "Poor": [0.30, None]},
                                    },
                                    "Resistivity at 90C": {
                                        ">170kV":     {"Poor": [0, 3],   "Fair": [3,   10],   "Good": [10,  None]},
                                        "72.5-170kV": {"Poor": [0, 0.2], "Fair": [0.2, 3],    "Good": [3,   None]},
                                        "<=72.5kV":   {"Poor": [0, 0.2], "Fair": [0.2, 3],    "Good": [3,   None]},
                                    },
                                    "Tan Delta at 90C": {
                                        # IEC 60422:2013 / IS 1866:2017 — dimensionless ratio (not %)
                                        ">170kV":     {"Good": [0, 0.010], "Fair": [0.010, 0.050], "Poor": [0.050, None]},
                                        "72.5-170kV": {"Good": [0, 0.020], "Fair": [0.020, 0.100], "Poor": [0.100, None]},
                                        "<=72.5kV":   {"Good": [0, 0.050], "Fair": [0.050, 0.200], "Poor": [0.200, None]},
                                    },
                                    "BDV Top (T)": {
                                        ">170kV":     {"Poor": [0, 50], "Fair": [50, 60], "Good": [60, None]},
                                        "72.5-170kV": {"Poor": [0, 40], "Fair": [40, 50], "Good": [50, None]},
                                        "<=72.5kV":   {"Poor": [0, 30], "Fair": [30, 40], "Good": [40, None]},
                                    },
                                    "BDV Bottom (B)": {
                                        ">170kV":     {"Poor": [0, 50], "Fair": [50, 60], "Good": [60, None]},
                                        "72.5-170kV": {"Poor": [0, 40], "Fair": [40, 50], "Good": [50, None]},
                                        "<=72.5kV":   {"Poor": [0, 30], "Fair": [30, 40], "Good": [40, None]},
                                    },
                                    # ── UPDATED per screenshot: Good >25, Fair 20-25, Poor <20 ──
                                    "Interfacial Tension": {
                                        ">170kV":     {"Good": [25, None], "Fair": [20, 25], "Poor": [0, 20]},
                                        "72.5-170kV": {"Good": [25, None], "Fair": [20, 25], "Poor": [0, 20]},
                                        "<=72.5kV":   {"Good": [25, None], "Fair": [20, 25], "Poor": [0, 20]},
                                    },
                                    # ── UPDATED per PDF: flat 125°C minimum, OK/NOT OK only ──
                                    "Flash Point": {
                                        ">170kV":     {"OK": [125, None], "NOT OK": [0, 125]},
                                        "72.5-170kV": {"OK": [125, None], "NOT OK": [0, 125]},
                                        "<=72.5kV":   {"OK": [125, None], "NOT OK": [0, 125]},
                                    },
                                    "Water Content": {
                                        ">170kV":     {"Good": [0, 15], "Fair": [15, 20], "Poor": [20, None]},
                                        "72.5-170kV": {"Good": [0, 20], "Fair": [20, 30], "Poor": [30, None]},
                                        "<=72.5kV":   {"Good": [0, 30], "Fair": [30, 40], "Poor": [40, None]},
                                    },
                                },
                            },
                        },
                    },
                    {"key": "remarks",        "label": "Remarks",         "type": "text"},
                ],
                "default_rows": [
                    {"test_name": "Acidity",              "unit": "mg KOH/g"},
                    {"test_name": "Resistivity at 90C",   "unit": "G ohm m"},
                    {"test_name": "Tan Delta at 90C",     "unit": ""},
                    {"test_name": "BDV Top (T)",          "unit": "kV"},
                    {"test_name": "BDV Bottom (B)",       "unit": "kV"},
                    {"test_name": "Interfacial Tension",  "unit": "mN/m"},
                    {"test_name": "Flash Point",          "unit": "°C"},
                    {"test_name": "Water Content",        "unit": "ppm"},
                ],
            },
        ],
        },

        # ── Dissolved Gas Analysis ───────────────────────────────────────────
        {
            "title": "Dissolved Gas Analysis (DGA)",
            "fields": [
                {
                    "key": "dga_standard",
                    "label": "Standard",
                    "type": "dropdown",
                    "options": ["IS 10593:2017", "IS 10593:2000", "IEC 60599:2022"],
                    "default": "IS 10593:2017",
                    "required": False,
                },
                {
                    "key": "dga_sample_location",
                    "label": "Sample Location",
                    "type": "dropdown",
                    "options": ["Bottom", "Top", "Middle", "Both (Top & Bottom)"],
                    "default": "Bottom",
                    "required": False,
                },
                {
                    "key": "dga_results",
                    "label": "Dissolved Gas Analysis Results (ppm)",
                    "type": "table",
                    "allow_add_rows": False,
                    "allow_delete_rows": False,
                    "columns": [
                        {"key": "gas",         "label": "Gas",            "type": "readonly"},
                        {"key": "formula",     "label": "Formula",        "type": "readonly"},
                        {"key": "value_top",   "label": "Top (ppm)",      "type": "number"},
                        {"key": "value_bottom","label": "Bottom (ppm)",   "type": "number"},
                        {
                            "key": "condition",
                            "label": "Status",
                            "type": "calculated",
                            "hidden": True,
                            "rule": {
                                "type": "THRESHOLD",
                                "config": {
                                    "input_field": "value_bottom",
                                    "lookup_fields": [
                                        "gas",
                                        {
                                            "field": "$form.dga_standard",
                                            "mapping": {
                                                "IS 10593:2017":  "IS 10593:2017",
                                                "IS 10593:2000":  "IS 10593:2000",
                                                "IEC 60599:2022": "IEC 60599:2022",
                                            },
                                        },
                                    ],
                                    "thresholds": {
                                        "Methane": {
                                            "IS 10593:2017":  {"Normal": [0, 30],    "Alert": [30,    130],   "Abnormal / Critical": [130,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 100],   "Alert": [100,   300],   "Abnormal / Critical": [300,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 30],    "Alert": [30,    130],   "Abnormal / Critical": [130,   None]},
                                        },
                                        "Ethane": {
                                            "IS 10593:2017":  {"Normal": [0, 20],    "Alert": [20,    90],    "Abnormal / Critical": [90,    None]},
                                            "IS 10593:2000":  {"Normal": [0, 300],   "Alert": [300,   1000],  "Abnormal / Critical": [1000,  None]},
                                            "IEC 60599:2022": {"Normal": [0, 20],    "Alert": [20,    90],    "Abnormal / Critical": [90,    None]},
                                        },
                                        "Ethylene": {
                                            "IS 10593:2017":  {"Normal": [0, 60],    "Alert": [60,    280],   "Abnormal / Critical": [280,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 100],   "Alert": [100,   400],   "Abnormal / Critical": [400,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 60],    "Alert": [60,    280],   "Abnormal / Critical": [280,   None]},
                                        },
                                        "Acetylene": {
                                            "IS 10593:2017":  {"Normal": [0, 2],     "Alert": [2,     20],    "Abnormal / Critical": [20,    None]},
                                            "IS 10593:2000":  {"Normal": [0, 50],    "Alert": [50,    200],   "Abnormal / Critical": [200,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 2],     "Alert": [2,     20],    "Abnormal / Critical": [20,    None]},
                                        },
                                        "Hydrogen": {
                                            "IS 10593:2017":  {"Normal": [0, 50],    "Alert": [50,    150],   "Abnormal / Critical": [150,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 100],   "Alert": [100,   300],   "Abnormal / Critical": [300,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 50],    "Alert": [50,    150],   "Abnormal / Critical": [150,   None]},
                                        },
                                        "Carbon Dioxide": {
                                            "IS 10593:2017":  {"Normal": [0, 3800],  "Alert": [3800,  14000], "Abnormal / Critical": [14000, None]},
                                            "IS 10593:2000":  {"Normal": [0, 5000],  "Alert": [5000,  12000], "Abnormal / Critical": [12000, None]},
                                            "IEC 60599:2022": {"Normal": [0, 3800],  "Alert": [3800,  14000], "Abnormal / Critical": [14000, None]},
                                        },
                                        "Carbon Monoxide": {
                                            "IS 10593:2017":  {"Normal": [0, 400],   "Alert": [400,   600],   "Abnormal / Critical": [600,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 300],   "Alert": [300,   700],   "Abnormal / Critical": [700,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 400],   "Alert": [400,   600],   "Abnormal / Critical": [600,   None]},
                                        },
                                        "TGC": {
                                            "IS 10593:2017":  {"Normal": [0, 200],   "Alert": [200,   500],   "Abnormal / Critical": [500,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 200],   "Alert": [200,   500],   "Abnormal / Critical": [500,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 200],   "Alert": [200,   500],   "Abnormal / Critical": [500,   None]},
                                        },
                                    },
                                },
                            },
                        },
                        {"key": "remarks", "label": "Remarks", "type": "text"},
                    ],
                    "default_rows": [
                        {"gas": "Methane",         "formula": "CH4"},
                        {"gas": "Ethane",          "formula": "C2H6"},
                        {"gas": "Ethylene",        "formula": "C2H4"},
                        {"gas": "Acetylene",       "formula": "C2H2"},
                        {"gas": "Hydrogen",        "formula": "H2"},
                        {"gas": "Carbon Dioxide",  "formula": "CO2"},
                        {"gas": "Carbon Monoxide", "formula": "CO"},
                        {"gas": "TGC",             "formula": "TGC"},
                    ],
                },
                {
                    "key": "dga_overall",
                    "label": "DGA Overall Assessment",
                    "type": "readonly",
                    "required": False,
                    "rule": {
                        "type": "AGGREGATE_STATUS",
                        "config": {
                            "sources": ["dga_results.condition"],
                            "priority": ["Abnormal / Critical", "Alert", "Normal"],
                            "value_map": {
                                "Alert":               "Alert — Monitor closely",
                                "Normal":              "Normal — Gases within limits",
                                "Abnormal / Critical": "Abnormal / Critical — Investigate",
                            },
                            "default": "Normal — Gases within limits",
                        },
                    },
                    "dropdown_evaluation": {
                        "enabled": True,
                        "value_severities": {
                            "Normal — Gases within limits":       "NORMAL",
                            "Alert — Monitor closely":            "ALERT",
                            "Abnormal / Critical — Investigate":  "CRITICAL",
                        },
                    },
                },
                {
                    "key": "dga_remarks",
                    "label": "DGA Remarks",
                    "type": "textarea",
                    "required": False,
                },
            ],
        },

        # ── Overall Assessment ────────────────────────────────────────────────
        {
            "title": "Overall Assessment",
            "fields": [
                {
                    "key": "overall_result",
                    "label": "Overall Result",
                    "type": "dropdown",
                    "options": ["PASS", "CONDITIONAL", "FAIL"],
                    "required": True,
                    "dropdown_evaluation": {
                        "enabled": True,
                        "value_severities": {
                            "PASS":        "NORMAL",
                            "CONDITIONAL": "ALERT",
                            "FAIL":        "CRITICAL",
                        },
                    },
                },
                {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
            ],
        },
    ],
},
   
    # ────────────────────────────────────────────────────────────────────────────
    # Dissolved Gas Analysis — standalone (Power Transformer)
    # Independent DGA sampling — not tied to a full oil test.
    # Thresholds per IS 10593:2017 (>10 yr transformer limits).
    # ────────────────────────────────────────────────────────────────────────────
    "transformer_dga": {
    "key": "transformer_dga",
    "name": "Transformer Dissolved Gas Analysis (DGA)",
    "equipment_type": "Power Transformer",
    "description": "Standalone DGA sampling as per IS 10593:2017 / IEC 60599.",
    "supports_multi_session": False,
    "typical_session_interval_days": 180,
    "typical_total_sessions": 1,
    "sections": [
        {
            "title": "Sample Details",
            "fields": [
                {
                    "key": "sample_reference",
                    "label": "Sample Reference No.",
                    "type": "text",
                    "required": False,
                },
                {
                    "key": "dga_standard",
                    "label": "Standard",
                    "type": "dropdown",
                    "options": ["IS 10593:2017", "IS 10593:2000", "IEC 60599:2022"],
                    "default": "IS 10593:2017",
                    "required": False,
                },
                {
                    "key": "sample_location",
                    "label": "Sample Location",
                    "type": "dropdown",
                    "options": ["Bottom", "Top", "Middle", "Both (Top & Bottom)"],
                    "default": "Bottom",
                    "required": True,
                },
                {
                    "key": "transformer_age_category",
                    "label": "Transformer Age",
                    "type": "dropdown",
                    "options": ["< 4 Years", "4–10 Years", "> 10 Years"],
                    "required": False,
                },
                {
                    "key": "oil_temperature_c",
                    "label": "Oil Temperature at Sampling",
                    "type": "number",
                    "unit": "°C",
                    "required": False,
                },
                {
                    "key": "load_at_sampling",
                    "label": "Load at Time of Sampling",
                    "type": "text",
                    "required": False,
                },
            ],
        },
        {
            "title": "Dissolved Gas Analysis Results",
            "fields": [
                {
                    "key": "dga_results",
                    "label": "Gas Concentrations (ppm)",
                    "type": "table",
                    "allow_add_rows": False,
                    "allow_delete_rows": False,
                    "columns": [
                        {"key": "gas",         "label": "Gas",            "type": "readonly"},
                        {"key": "formula",     "label": "Formula",        "type": "readonly"},
                        {"key": "value_top",   "label": "Top (ppm)",      "type": "number"},
                        {"key": "value_bottom","label": "Bottom (ppm)",   "type": "number"},
                        {
                            "key": "condition",
                            "label": "Status",
                            "type": "calculated",
                            "hidden": True,
                            "rule": {
                                "type": "THRESHOLD",
                                "config": {
                                    "input_field": "value_bottom",
                                    "lookup_fields": [
                                        "gas",
                                        {
                                            "field": "$form.dga_standard",
                                            "mapping": {
                                                "IS 10593:2017":  "IS 10593:2017",
                                                "IS 10593:2000":  "IS 10593:2000",
                                                "IEC 60599:2022": "IEC 60599:2022",
                                            },
                                        },
                                    ],
                                    "thresholds": {
                                        "Methane": {
                                            "IS 10593:2017":  {"Normal": [0, 30],    "Alert": [30,    130],   "Abnormal / Critical": [130,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 100],   "Alert": [100,   300],   "Abnormal / Critical": [300,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 30],    "Alert": [30,    130],   "Abnormal / Critical": [130,   None]},
                                        },
                                        "Ethane": {
                                            "IS 10593:2017":  {"Normal": [0, 20],    "Alert": [20,    90],    "Abnormal / Critical": [90,    None]},
                                            "IS 10593:2000":  {"Normal": [0, 300],   "Alert": [300,   1000],  "Abnormal / Critical": [1000,  None]},
                                            "IEC 60599:2022": {"Normal": [0, 20],    "Alert": [20,    90],    "Abnormal / Critical": [90,    None]},
                                        },
                                        "Ethylene": {
                                            "IS 10593:2017":  {"Normal": [0, 60],    "Alert": [60,    280],   "Abnormal / Critical": [280,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 100],   "Alert": [100,   400],   "Abnormal / Critical": [400,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 60],    "Alert": [60,    280],   "Abnormal / Critical": [280,   None]},
                                        },
                                        "Acetylene": {
                                            "IS 10593:2017":  {"Normal": [0, 2],     "Alert": [2,     20],    "Abnormal / Critical": [20,    None]},
                                            "IS 10593:2000":  {"Normal": [0, 50],    "Alert": [50,    200],   "Abnormal / Critical": [200,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 2],     "Alert": [2,     20],    "Abnormal / Critical": [20,    None]},
                                        },
                                        "Hydrogen": {
                                            "IS 10593:2017":  {"Normal": [0, 50],    "Alert": [50,    150],   "Abnormal / Critical": [150,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 100],   "Alert": [100,   300],   "Abnormal / Critical": [300,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 50],    "Alert": [50,    150],   "Abnormal / Critical": [150,   None]},
                                        },
                                        "Carbon Dioxide": {
                                            "IS 10593:2017":  {"Normal": [0, 3800],  "Alert": [3800,  14000], "Abnormal / Critical": [14000, None]},
                                            "IS 10593:2000":  {"Normal": [0, 5000],  "Alert": [5000,  12000], "Abnormal / Critical": [12000, None]},
                                            "IEC 60599:2022": {"Normal": [0, 3800],  "Alert": [3800,  14000], "Abnormal / Critical": [14000, None]},
                                        },
                                        "Carbon Monoxide": {
                                            "IS 10593:2017":  {"Normal": [0, 400],   "Alert": [400,   600],   "Abnormal / Critical": [600,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 300],   "Alert": [300,   700],   "Abnormal / Critical": [700,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 400],   "Alert": [400,   600],   "Abnormal / Critical": [600,   None]},
                                        },
                                        "TGC": {
                                            "IS 10593:2017":  {"Normal": [0, 200],   "Alert": [200,   500],   "Abnormal / Critical": [500,   None]},
                                            "IS 10593:2000":  {"Normal": [0, 200],   "Alert": [200,   500],   "Abnormal / Critical": [500,   None]},
                                            "IEC 60599:2022": {"Normal": [0, 200],   "Alert": [200,   500],   "Abnormal / Critical": [500,   None]},
                                        },
                                    },
                                },
                            },
                        },
                        {"key": "remarks", "label": "Remarks", "type": "text"},
                    ],
                    "default_rows": [
                        {"gas": "Methane",         "formula": "CH4"},
                        {"gas": "Ethane",          "formula": "C2H6"},
                        {"gas": "Ethylene",        "formula": "C2H4"},
                        {"gas": "Acetylene",       "formula": "C2H2"},
                        {"gas": "Hydrogen",        "formula": "H2"},
                        {"gas": "Carbon Dioxide",  "formula": "CO2"},
                        {"gas": "Carbon Monoxide", "formula": "CO"},
                        {"gas": "TGC",             "formula": "TGC"},
                    ],
                },
            ],
        },
        {
            "title": "Assessment",
            "fields": [
                {
                    "key": "overall_assessment",
                    "label": "Overall DGA Assessment",
                    "type": "dropdown",
                    "options": [
                        "Normal — Gases within limits",
                        "Alert — Monitor closely",
                        "Abnormal / Critical — Investigate immediately",
                    ],
                    "required": False,
                    "dropdown_evaluation": {
                        "enabled": True,
                        "value_severities": {
                            "Normal — Gases within limits":             "NORMAL",
                            "Alert — Monitor closely":                  "ALERT",
                            "Abnormal / Critical — Investigate immediately": "CRITICAL",
                        },
                    },
                },
                {
                    "key": "key_gases_identified",
                    "label": "Key Gas(es) of Concern",
                    "type": "text",
                    "required": False,
                },
                {
                    "key": "probable_fault",
                    "label": "Probable Fault Type",
                    "type": "dropdown",
                    "options": [
                        "None — Normal aging",
                        "Partial Discharge",
                        "Low-energy Discharge",
                        "High-energy Discharge (Arcing)",
                        "Thermal Fault < 300°C",
                        "Thermal Fault 300–700°C",
                        "Thermal Fault > 700°C",
                        "Cellulose Degradation",
                        "Inconclusive",
                    ],
                    "required": False,
                },
                {
                    "key": "recommended_action",
                    "label": "Recommended Action",
                    "type": "dropdown",
                    "options": [
                        "Continue normal monitoring",
                        "Increase monitoring frequency",
                        "Schedule detailed investigation",
                        "Take offline for inspection",
                    ],
                    "required": False,
                },
                {
                    "key": "remarks",
                    "label": "Remarks",
                    "type": "textarea",
                    "required": False,
                },
            ],
        },
    ],
},

    # ────────────────────────────────────────────────────────────────────────────
    # Capacitance & Tan Delta Test (Transformer) — KPTCL R&D Centre format
    # Covers: winding C/tanδ + 220kV bushing + 66kV bushing + IDAX insulation diagnostics.
    # ITC correction factor stored at section level (one factor per section, not per row).
    # df_corrected_20c is auto-calculated via FORMULA rule (PRODUCT of df_measured * form-level ITC factor).
    # ────────────────────────────────────────────────────────────────────────────
 "capacitance_tandelta_transformer": {
    "key": "capacitance_tandelta_transformer",
    "name": "Capacitance & Tan Delta Test (Transformer)",
    "equipment_type": "Power Transformer",
    "description": "Combined Tan-Delta/Capacitance and IDAX insulation diagnostics per KPTCL R&D Centre format — winding, 400kV/220kV/66kV/33kV/11kV bushing, and moisture/oil conductivity measurements. Supports 220/66/11kV and 400/220/33kV transformer types.",
    "supports_multi_session": False,
    "typical_session_interval_days": None,
    "typical_total_sessions": 1,
    "context_bindings": {
        "sub_station":         "equipment.department_name",
        "make":                "equipment.manufacturer",
        "capacity_mva":        "nameplate.rated_mva",
        "serial_number":       "equipment.factory_serial_number",
        "year_of_manufacture": "equipment.year_of_manufacture",
        "vector_group":        "equipment.vector_group",
        "voltage_ratio":       "equipment.voltage_class",
    },
    "sections": [
        # ── Equipment Details (auto-filled) ──────────────────────────────
        {
            "title": "Equipment Details",
            "collapsed": True,
            "fields": [
                {"key": "sub_station",         "label": "Sub Station",         "type": "readonly"},
                {"key": "make",                "label": "Manufacturer",        "type": "readonly"},
                {"key": "serial_number",       "label": "Serial Number",       "type": "readonly"},
                {"key": "capacity_mva",        "label": "Rated MVA",           "type": "readonly"},
                {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "readonly"},
                {"key": "vector_group",        "label": "Vector Group",        "type": "readonly"},
                {"key": "voltage_ratio",       "label": "Voltage Ratio",       "type": "readonly"},
                {
                    "key": "transformer_type",
                    "label": "Transformer Type",
                    "type": "dropdown",
                    "options": ["220/66/11 kV", "400/220/33 kV"],
                    "required": True,
                    "import_skip": True,
                },
            ],
        },
        # ── Test Conditions ───────────────────────────────────────────────
        {
            "title": "Test Conditions",
            "collapsible": True,
            "collapse_control": {
                "key": "test_conditions_enabled",
                "label": "Test Conditions",
                "type": "section_toggle",
                "default": "open",
                "options": ["open", "skip"],
            },
            "fields": [
                {"key": "frequency_hz",      "label": "Supply Frequency",      "type": "number", "unit": "Hz",  "required": True, "default": "50"},
                {"key": "ambient_temp_c",    "label": "Ambient Temperature",   "type": "number", "unit": "°C", "required": True},
                {"key": "oil_temp_c",        "label": "Oil Temperature",       "type": "number", "unit": "°C"},
                {"key": "weather_condition", "label": "Weather Condition",     "type": "text",   "placeholder": "e.g. Cloudy, Sunny"},
                {"key": "instrument_make",   "label": "Instrument Make/Model", "type": "text",   "placeholder": "e.g. Megger IDAX 300"},
            ],
        },
        # ── Winding Test Results ──────────────────────────────────────────
        {
            "title": "Winding Test Results",
            "collapsible": True,
            "collapse_control": {
                "key": "winding_enabled",
                "label": "Winding Test",
                "type": "section_toggle",
                "default": "open",
                "options": ["open", "skip"],
            },
            "fields": [
                {"key": "winding_itc_factor", "label": "ITC Correction Factor (Winding)", "type": "number"},
                # ── NEW: previous test date for this table (one date applies to whole winding table) ──
                {
                    "key": "winding_previous_test_date",
                    "label": "Previous Test Date (Winding)",
                    "type": "date",
                    "placeholder": "Select date of previous winding test",
                },
                {
                    "key": "winding_test_results",
                    "label": "Winding Test Data",
                    "type": "table",
                    "allow_add_rows": True,
                    "allow_delete_rows": True,
                    "lock_default_rows": False,
                    "columns": [
                        {"key": "test_configuration", "label": "Test Configuration", "type": "text",   "placeholder": "e.g. HV-GND, CHG, HV-Ground, HV-IV"},
                        {"key": "voltage_kv",          "label": "kV",                "type": "number", "unit": "kV"},
                        {"key": "capacitance_pf",      "label": "Capacitance C (pF)","type": "number", "unit": "pF"},
                        {"key": "df_measured",         "label": "% D.F Measured",    "type": "number", "unit": "%"},
                        {
                            "key": "df_corrected_20c",
                            "label": "% D.F @ 20°C (ITC Corrected)",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "FORMULA",
                                "config": {
                                    "formula": "PRODUCT",
                                    "inputs": {"a": "df_measured", "b": "$form.winding_itc_factor"},
                                    "precision": 4,
                                },
                            },
                        },
                        # ── NEW: previous test's corrected %D.F, entered manually for now ──
                        {
                            "key": "df_previous_corrected",
                            "label": "% D.F @ 20°C (Previous Test)",
                            "type": "number",
                            "unit": "%",
                            "placeholder": "Enter value from previous test report",
                        },
                        {
                            "key": "condition",
                            "label": "Condition",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "THRESHOLD",
                                "config": {
                                    "input_field": "df_corrected_20c",
                                    "thresholds": {
                                        "Winding % D.F @ 20°C (IEEE/IEC)": {
                                            "Good": [None, 0.5],
                                            "Fair": [0.5,  1.0],
                                            "Poor": [1.0,  None],
                                        }
                                    },
                                },
                            },
                        },
                    ],
                    "default_rows": [
                        {"test_configuration": "HV-GND"},
                        {"test_configuration": "HV-LV"},
                        {"test_configuration": "LV-GND"},
                        {"test_configuration": "LV-TV"},
                        {"test_configuration": "TV-GND"},
                        {"test_configuration": "HV-TV"},
                        {"test_configuration": "(HV+LV)-GND"},
                        {"test_configuration": "(HV+LV)-TV"},
                    ],
                    "table_evaluation": {
                        "enabled": True,
                        "column_evaluations": {
                            "df_corrected_20c": {
                                "normal_min": None, "normal_max": 0.5,
                                "alert_min":  None, "alert_max":  None,
                                "critical_below": None, "critical_above": 1.0,
                                "trend_watch": True,
                                "weight": 2.0,
                                "remedial_action_text": "Winding insulation deteriorating — schedule drying or oil reconditioning.",
                            },
                        },
                    },
                },
                {"key": "winding_observations", "label": "Observations (Winding)", "type": "textarea"},
            ],
        },

        # ═══════════════════════════════════════════════════════════════════
        # BUSHING TEST RESULTS — one separate section per voltage class.
        # Each section is independently collapsible (skip if not applicable).
        # 220/66/11 kV transformer  → use 220kV + 66kV sections
        # 400/220/33 kV transformer → use 400kV + 220kV + 33kV sections
        # ═══════════════════════════════════════════════════════════════════

        # ── 400 kV Bushing Test Results ───────────────────────────────────
        # Applicable to 400/220/33 kV transformers only.
        {
            "title": "400 kV Bushing Test Results",
            "collapsible": True,
            "collapse_control": {
                "key": "bushing_400kv_enabled",
                "label": "400 kV Bushing Test",
                "type": "section_toggle",
                "default": "skip",          # default skip — only open for 400kV transformers
                "options": ["open", "skip"],
            },
            "fields": [
                {"key": "bushing_400kv_itc_factor", "label": "ITC Correction Factor (400 kV Bushing)", "type": "number"},
                # ── NEW: previous test date for this table ──
                {
                    "key": "bushing_400kv_previous_test_date",
                    "label": "Previous Test Date (400 kV Bushing)",
                    "type": "date",
                    "placeholder": "Select date of previous 400 kV bushing test",
                },
                {
                    "key": "bushing_400kv_test_results",
                    "label": "400 kV Bushing Test Data",
                    "type": "table",
                    "allow_add_rows": True,
                    "allow_delete_rows": True,
                    "lock_default_rows": False,
                    "columns": [
                        {"key": "bushing",          "label": "Bushing",                        "type": "text",   "placeholder": "e.g. 'R' Phase"},
                        {"key": "voltage_kv",        "label": "kV",                             "type": "number", "unit": "kV"},
                        {"key": "capacitance_pf",    "label": "Capacitance C (pF)",             "type": "number", "unit": "pF"},
                        {"key": "df_measured",       "label": "% D.F Measured",                 "type": "number", "unit": "%"},
                        {
                            "key": "df_corrected_20c",
                            "label": "% D.F @ 20°C (ITC Corrected)",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "FORMULA",
                                "config": {
                                    "formula": "PRODUCT",
                                    "inputs": {"a": "df_measured", "b": "$form.bushing_400kv_itc_factor"},
                                    "precision": 4,
                                },
                            },
                        },
                        # ── NEW: previous test's corrected %D.F, entered manually for now ──
                        {
                            "key": "df_previous_corrected",
                            "label": "% D.F @ 20°C (Previous Test)",
                            "type": "number",
                            "unit": "%",
                            "placeholder": "Enter value from previous test report",
                        },
                        {
                            "key": "condition",
                            "label": "Condition",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "THRESHOLD",
                                "config": {
                                    "input_field": "df_corrected_20c",
                                    "thresholds": {
                                        "400 kV Bushing % D.F @ 20°C (IEC OIP)": {
                                            "Good":  [None, 0.5],
                                            "Alert": [0.5,  0.7],
                                            "Poor":  [0.7,  None],
                                        }
                                    },
                                },
                            },
                        },
                    ],
                    "default_rows": [
                        {"bushing": "'R' Phase"},
                        {"bushing": "'Y' Phase"},
                        {"bushing": "'B' Phase"},
                    ],
                    "table_evaluation": {
                        "enabled": True,
                        "column_evaluations": {
                            "df_corrected_20c": {
                                "normal_min": None, "normal_max": 0.5,
                                "alert_min":  0.5,  "alert_max":  0.7,
                                "critical_below": None, "critical_above": 0.7,
                                "trend_watch": True,
                                "weight": 1.5,
                                "remedial_action_text": "400 kV bushing insulation degraded — inspect and consider replacement.",
                            },
                        },
                    },
                },
                {"key": "bushing_400kv_observations", "label": "Observations (400 kV Bushing)", "type": "textarea"},
            ],
        },

        # ── 220 kV Bushing Test Results ───────────────────────────────────
        # Applicable to BOTH transformer types:
        #   220/66/11 kV  → primary HV bushing
        #   400/220/33 kV → secondary MV bushing
        {
            "title": "220 kV Bushing Test Results",
            "collapsible": True,
            "collapse_control": {
                "key": "bushing_220kv_enabled",
                "label": "220 kV Bushing Test",
                "type": "section_toggle",
                "default": "open",
                "options": ["open", "skip"],
            },
            "fields": [
                {"key": "bushing_220kv_itc_factor", "label": "ITC Correction Factor (220 kV Bushing)", "type": "number"},
                # ── NEW: previous test date for this table ──
                {
                    "key": "bushing_220kv_previous_test_date",
                    "label": "Previous Test Date (220 kV Bushing)",
                    "type": "date",
                    "placeholder": "Select date of previous 220 kV bushing test",
                },
                {
                    "key": "bushing_220kv_test_results",
                    "label": "220 kV Bushing Test Data",
                    "type": "table",
                    "allow_add_rows": True,
                    "allow_delete_rows": True,
                    "lock_default_rows": False,
                    "columns": [
                        {"key": "bushing",          "label": "Bushing",                        "type": "text",   "placeholder": "e.g. 'R' Phase"},
                        {"key": "voltage_kv",        "label": "kV",                             "type": "number", "unit": "kV"},
                        {"key": "capacitance_pf",    "label": "Capacitance C (pF)",             "type": "number", "unit": "pF"},
                        {"key": "df_measured",       "label": "% D.F Measured",                 "type": "number", "unit": "%"},
                        {
                            "key": "df_corrected_20c",
                            "label": "% D.F @ 20°C (ITC Corrected)",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "FORMULA",
                                "config": {
                                    "formula": "PRODUCT",
                                    "inputs": {"a": "df_measured", "b": "$form.bushing_220kv_itc_factor"},
                                    "precision": 4,
                                },
                            },
                        },
                        # ── NEW: previous test's corrected %D.F, entered manually for now ──
                        {
                            "key": "df_previous_corrected",
                            "label": "% D.F @ 20°C (Previous Test)",
                            "type": "number",
                            "unit": "%",
                            "placeholder": "Enter value from previous test report",
                        },
                        {
                            "key": "condition",
                            "label": "Condition",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "THRESHOLD",
                                "config": {
                                    "input_field": "df_corrected_20c",
                                    "thresholds": {
                                        "220 kV Bushing % D.F @ 20°C (IEC OIP)": {
                                            "Good":  [None, 0.5],
                                            "Alert": [0.5,  0.7],
                                            "Poor":  [0.7,  None],
                                        }
                                    },
                                },
                            },
                        },
                    ],
                    "default_rows": [
                        {"bushing": "'R' Phase"},
                        {"bushing": "'Y' Phase"},
                        {"bushing": "'B' Phase"},
                    ],
                    "table_evaluation": {
                        "enabled": True,
                        "column_evaluations": {
                            "df_corrected_20c": {
                                "normal_min": None, "normal_max": 0.5,
                                "alert_min":  0.5,  "alert_max":  0.7,
                                "critical_below": None, "critical_above": 0.7,
                                "trend_watch": True,
                                "weight": 1.5,
                                "remedial_action_text": "220 kV bushing insulation degraded — inspect and consider replacement.",
                            },
                        },
                    },
                },
                {"key": "bushing_220kv_observations", "label": "Observations (220 kV Bushing)", "type": "textarea"},
            ],
        },

        # ── 66 kV Bushing Test Results ────────────────────────────────────
        # Applicable to 220/66/11 kV transformers (LV bushing).
        {
            "title": "66 kV Bushing Test Results",
            "collapsible": True,
            "collapse_control": {
                "key": "bushing_66kv_enabled",
                "label": "66 kV Bushing Test",
                "type": "section_toggle",
                "default": "open",
                "options": ["open", "skip"],
            },
            "fields": [
                {"key": "bushing_66kv_itc_factor", "label": "ITC Correction Factor (66 kV Bushing)", "type": "number"},
                # ── NEW: previous test date for this table ──
                {
                    "key": "bushing_66kv_previous_test_date",
                    "label": "Previous Test Date (66 kV Bushing)",
                    "type": "date",
                    "placeholder": "Select date of previous 66 kV bushing test",
                },
                {
                    "key": "bushing_66kv_test_results",
                    "label": "66 kV Bushing Test Data",
                    "type": "table",
                    "allow_add_rows": True,
                    "allow_delete_rows": True,
                    "lock_default_rows": False,
                    "columns": [
                        {"key": "bushing",          "label": "Bushing",                       "type": "text",   "placeholder": "e.g. 'R' Phase"},
                        {"key": "voltage_kv",        "label": "kV",                            "type": "number", "unit": "kV"},
                        {"key": "capacitance_pf",    "label": "Capacitance C (pF)",            "type": "number", "unit": "pF"},
                        {"key": "df_measured",       "label": "% D.F Measured",                "type": "number", "unit": "%"},
                        {
                            "key": "df_corrected_20c",
                            "label": "% D.F @ 20°C (ITC Corrected)",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "FORMULA",
                                "config": {
                                    "formula": "PRODUCT",
                                    "inputs": {"a": "df_measured", "b": "$form.bushing_66kv_itc_factor"},
                                    "precision": 4,
                                },
                            },
                        },
                        # ── NEW: previous test's corrected %D.F, entered manually for now ──
                        {
                            "key": "df_previous_corrected",
                            "label": "% D.F @ 20°C (Previous Test)",
                            "type": "number",
                            "unit": "%",
                            "placeholder": "Enter value from previous test report",
                        },
                        {
                            "key": "condition",
                            "label": "Condition",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "THRESHOLD",
                                "config": {
                                    "input_field": "df_corrected_20c",
                                    "thresholds": {
                                        "66 kV Bushing % D.F @ 20°C (IEC OIP)": {
                                            "Good":  [None, 0.7],
                                            "Alert": [0.7,  1.0],
                                            "Poor":  [1.0,  None],
                                        }
                                    },
                                },
                            },
                        },
                    ],
                    "default_rows": [
                        {"bushing": "'R' Phase"},
                        {"bushing": "'Y' Phase"},
                        {"bushing": "'B' Phase"},
                    ],
                    "table_evaluation": {
                        "enabled": True,
                        "column_evaluations": {
                            "df_corrected_20c": {
                                "normal_min": None, "normal_max": 0.7,
                                "alert_min":  0.7,  "alert_max":  1.0,
                                "critical_below": None, "critical_above": 1.0,
                                "trend_watch": True,
                                "weight": 1.5,
                                "remedial_action_text": "66 kV bushing insulation degraded — inspect and consider replacement.",
                            },
                        },
                    },
                },
                {"key": "bushing_66kv_observations", "label": "Observations (66 kV Bushing)", "type": "textarea"},
            ],
        },

        # ── 33 kV Bushing Test Results ────────────────────────────────────
        # Applicable to 400/220/33 kV transformers (TV bushing).
        {
            "title": "33 kV Bushing Test Results",
            "collapsible": True,
            "collapse_control": {
                "key": "bushing_33kv_enabled",
                "label": "33 kV Bushing Test",
                "type": "section_toggle",
                "default": "skip",          # default skip — only open for 400/220/33kV
                "options": ["open", "skip"],
            },
            "fields": [
                {"key": "bushing_33kv_itc_factor", "label": "ITC Correction Factor (33 kV Bushing)", "type": "number"},
                # ── NEW: previous test date for this table ──
                {
                    "key": "bushing_33kv_previous_test_date",
                    "label": "Previous Test Date (33 kV Bushing)",
                    "type": "date",
                    "placeholder": "Select date of previous 33 kV bushing test",
                },
                {
                    "key": "bushing_33kv_test_results",
                    "label": "33 kV Bushing Test Data",
                    "type": "table",
                    "allow_add_rows": True,
                    "allow_delete_rows": True,
                    "lock_default_rows": False,
                    "columns": [
                        {"key": "bushing",          "label": "Bushing",                       "type": "text",   "placeholder": "e.g. 'R' Phase"},
                        {"key": "voltage_kv",        "label": "kV",                            "type": "number", "unit": "kV"},
                        {"key": "capacitance_pf",    "label": "Capacitance C (pF)",            "type": "number", "unit": "pF"},
                        {"key": "df_measured",       "label": "% D.F Measured",                "type": "number", "unit": "%"},
                        {
                            "key": "df_corrected_20c",
                            "label": "% D.F @ 20°C (ITC Corrected)",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "FORMULA",
                                "config": {
                                    "formula": "PRODUCT",
                                    "inputs": {"a": "df_measured", "b": "$form.bushing_33kv_itc_factor"},
                                    "precision": 4,
                                },
                            },
                        },
                        # ── NEW: previous test's corrected %D.F, entered manually for now ──
                        {
                            "key": "df_previous_corrected",
                            "label": "% D.F @ 20°C (Previous Test)",
                            "type": "number",
                            "unit": "%",
                            "placeholder": "Enter value from previous test report",
                        },
                        {
                            "key": "condition",
                            "label": "Condition",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "THRESHOLD",
                                "config": {
                                    "input_field": "df_corrected_20c",
                                    "thresholds": {
                                        "33 kV Bushing % D.F @ 20°C (IEC OIP)": {
                                            "Good":  [None, 1.0],
                                            "Alert": [1.0,  1.5],
                                            "Poor":  [1.5,  None],
                                        }
                                    },
                                },
                            },
                        },
                    ],
                    "default_rows": [
                        {"bushing": "'R' Phase"},
                        {"bushing": "'Y' Phase"},
                        {"bushing": "'B' Phase"},
                    ],
                    "table_evaluation": {
                        "enabled": True,
                        "column_evaluations": {
                            "df_corrected_20c": {
                                "normal_min": None, "normal_max": 1.0,
                                "alert_min":  1.0,  "alert_max":  1.5,
                                "critical_below": None, "critical_above": 1.5,
                                "trend_watch": True,
                                "weight": 1.0,
                                "remedial_action_text": "33 kV bushing insulation degraded — inspect and consider replacement.",
                            },
                        },
                    },
                },
                {"key": "bushing_33kv_observations", "label": "Observations (33 kV Bushing)", "type": "textarea"},
            ],
        },

        # ── 11 kV Bushing Test Results ────────────────────────────────────
        # Applicable to 220/66/11 kV transformers (TV bushing).
        {
            "title": "11 kV Bushing Test Results",
            "collapsible": True,
            "collapse_control": {
                "key": "bushing_11kv_enabled",
                "label": "11 kV Bushing Test",
                "type": "section_toggle",
                "default": "skip",          # default skip — fill only if 11kV bushing tested
                "options": ["open", "skip"],
            },
            "fields": [
                {"key": "bushing_11kv_itc_factor", "label": "ITC Correction Factor (11 kV Bushing)", "type": "number"},
                # ── NEW: previous test date for this table ──
                {
                    "key": "bushing_11kv_previous_test_date",
                    "label": "Previous Test Date (11 kV Bushing)",
                    "type": "date",
                    "placeholder": "Select date of previous 11 kV bushing test",
                },
                {
                    "key": "bushing_11kv_test_results",
                    "label": "11 kV Bushing Test Data",
                    "type": "table",
                    "allow_add_rows": True,
                    "allow_delete_rows": True,
                    "lock_default_rows": False,
                    "columns": [
                        {"key": "bushing",          "label": "Bushing",                       "type": "text",   "placeholder": "e.g. 'R' Phase"},
                        {"key": "voltage_kv",        "label": "kV",                            "type": "number", "unit": "kV"},
                        {"key": "capacitance_pf",    "label": "Capacitance C (pF)",            "type": "number", "unit": "pF"},
                        {"key": "df_measured",       "label": "% D.F Measured",                "type": "number", "unit": "%"},
                        {
                            "key": "df_corrected_20c",
                            "label": "% D.F @ 20°C (ITC Corrected)",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "FORMULA",
                                "config": {
                                    "formula": "PRODUCT",
                                    "inputs": {"a": "df_measured", "b": "$form.bushing_11kv_itc_factor"},
                                    "precision": 4,
                                },
                            },
                        },
                        # ── NEW: previous test's corrected %D.F, entered manually for now ──
                        {
                            "key": "df_previous_corrected",
                            "label": "% D.F @ 20°C (Previous Test)",
                            "type": "number",
                            "unit": "%",
                            "placeholder": "Enter value from previous test report",
                        },
                        {
                            "key": "condition",
                            "label": "Condition",
                            "type": "calculated",
                            "read_only": True,
                            "rule": {
                                "type": "THRESHOLD",
                                "config": {
                                    "input_field": "df_corrected_20c",
                                    "thresholds": {
                                        "11 kV Bushing % D.F @ 20°C (IEC OIP)": {
                                            "Good":  [None, 1.0],
                                            "Alert": [1.0,  1.5],
                                            "Poor":  [1.5,  None],
                                        }
                                    },
                                },
                            },
                        },
                    ],
                    "default_rows": [
                        {"bushing": "'R' Phase"},
                        {"bushing": "'Y' Phase"},
                        {"bushing": "'B' Phase"},
                    ],
                    "table_evaluation": {
                        "enabled": True,
                        "column_evaluations": {
                            "df_corrected_20c": {
                                "normal_min": None, "normal_max": 1.0,
                                "alert_min":  1.0,  "alert_max":  1.5,
                                "critical_below": None, "critical_above": 1.5,
                                "trend_watch": True,
                                "weight": 1.0,
                                "remedial_action_text": "11 kV bushing insulation degraded — inspect and consider replacement.",
                            },
                        },
                    },
                },
                {"key": "bushing_11kv_observations", "label": "Observations (11 kV Bushing)", "type": "textarea"},
            ],
        },

        # ── IDAX Insulation Diagnostics ───────────────────────────────────
        {
            "title": "IDAX Test Results (Insulation Diagnostics)",
            "collapsible": True,
            "collapse_control": {
                "key": "idax_enabled",
                "label": "IDAX Test",
                "type": "section_toggle",
                "default": "open",
                "options": ["open", "skip"],
            },
            "fields": [
                {"key": "idax_testing_kit", "label": "Testing Kit Used", "type": "text", "placeholder": "e.g. Megger IDAX 300"},
                # ── NEW: previous test date for this table ──
                {
                    "key": "idax_previous_test_date",
                    "label": "Previous Test Date (IDAX)",
                    "type": "date",
                    "placeholder": "Select date of previous IDAX test",
                },
                {
                    "key": "idax_test_results",
                    "label": "IDAX Test Data",
                    "type": "table",
                    "allow_add_rows": True,
                    "allow_delete_rows": True,
                    "lock_default_rows": False,
                    "columns": [
                        {"key": "test_configuration",    "label": "Test Configuration",              "type": "text",   "placeholder": "e.g. HV-GND, CHG, HV-Ground"},
                        {"key": "moisture_percent",      "label": "% Moisture",                      "type": "number", "unit": "%"},
                        # ── NEW: previous test's %Moisture, entered manually for now ──
                        {
                            "key": "moisture_percent_previous",
                            "label": "% Moisture (Previous Test)",
                            "type": "number",
                            "unit": "%",
                            "placeholder": "Enter value from previous test report",
                        },
                        {
                            "key": "tr_analysis_moisture",
                            "label": "Tr. Analysis (% Moisture)",
                            "type": "dropdown",
                            "options": ["As new", "Dry", "Moderately Wet", "Wet", "Very Wet"],
                        },
                        {"key": "oil_conductivity_psm",  "label": "Oil Conductivity (pS/m)",         "type": "number", "unit": "pS/m"},
                        {
                            "key": "tr_analysis_oil",
                            "label": "Tr. Analysis (Oil Conductivity)",
                            "type": "dropdown",
                            "options": ["As new", "Acceptable", "Poor", "Bad"],
                        },
                    ],
                    "default_rows": [
                        {"test_configuration": "HV-GND"},
                        {"test_configuration": "HV-LV"},
                        {"test_configuration": "LV-GND"},
                        {"test_configuration": "LV-TV"},
                        {"test_configuration": "TV-GND"},
                        {"test_configuration": "HV-TV"},
                        {"test_configuration": "(HV+LV)-GND"},
                        {"test_configuration": "(HV+LV)-TV"},
                    ],
                    "table_evaluation": {
                        "enabled": True,
                        "column_evaluations": {
                            "moisture_percent": {
                                "normal_min": None, "normal_max": 2.0,
                                "alert_min":  None, "alert_max":  None,
                                "critical_below": None, "critical_above": 3.0,
                                "trend_watch": True,
                                "weight": 2.0,
                                "remedial_action_text": "High moisture content — arrange drying treatment.",
                            },
                            "oil_conductivity_psm": {
                                "normal_min": None, "normal_max": 0.1,
                                "alert_min":  None, "alert_max":  None,
                                "critical_below": None, "critical_above": 1.0,
                                "trend_watch": True,
                                "weight": 1.0,
                                "remedial_action_text": "High oil conductivity — arrange oil reconditioning or replacement.",
                            },
                        },
                    },
                },
                {"key": "idax_observation", "label": "Observation", "type": "textarea"},
            ],
        },

        # ── Overall Assessment ────────────────────────────────────────────
        {
            "title": "Overall Assessment",
            "fields": [
                {
                    "key": "overall_result",
                    "label": "Overall Result",
                    "type": "dropdown",
                    "options": ["PASS", "CONDITIONAL", "FAIL"],
                    "required": True,
                    "dropdown_evaluation": {
                        "enabled": True,
                        "value_severities": {
                            "PASS":        "NORMAL",
                            "CONDITIONAL": "ALERT",
                            "FAIL":        "CRITICAL",
                        },
                    },
                },
                {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
            ],
        },
    ],
},
    # CIRCUIT BREAKER TEMPLATES
    # ════════════════════════════════════════════════════════════════════════════
 
  "circuit_breaker_contact_resistance": {
        "key": "circuit_breaker_contact_resistance",
        "name": "Contact Resistance Test",
        "equipment_type": "Circuit Breaker",
        "description": "Contact resistance measurement of circuit breaker poles using micro-ohmmeter.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "cb_make":         "equipment.manufacturer",
            "cb_serial":       "equipment.factory_serial_number",
            "voltage_class_kv":"equipment.voltage_class",
            "rated_current_a": "nameplate.rated_current",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "cb_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "cb_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                    {"key": "rated_current_a", "label": "Rated Current", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "cb_model",        "label": "CB Model",            "type": "text"},
                    {"key": "instrument_used", "label": "Instrument Used",     "type": "text"},
                    {"key": "test_current_a",  "label": "Test Current (DLRO)", "type": "number", "unit": "A"},
                ],
            },
            {
                "title": "Contact Resistance Readings",
                "fields": [
                    {
                        "key": "resistance_readings",
                        "label": "Resistance per Pole (µΩ)",
                        "type": "table",
                        "columns": [
                            {"key": "pole",          "label": "Pole",           "type": "text"},
                            {"key": "reading_1",     "label": "Reading 1 (µΩ)", "type": "number"},
                            {"key": "reading_2",     "label": "Reading 2 (µΩ)", "type": "number"},
                            {"key": "average",       "label": "Average (µΩ)",   "type": "number"},
                            {"key": "max_limit",     "label": "Max Limit (µΩ)", "type": "number"},
                            {"key": "result",        "label": "Result",         "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF},
                        ],
                        "default_rows": [
                            {"pole": "R Phase"},
                            {"pole": "Y Phase"},
                            {"pole": "B Phase"},
                        ],
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",         "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result",  "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Conditional"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFC}},
                    {"key": "tested_by",      "label": "Tested By",       "type": "text",     "required": True},
                ],
            },
        ],
    },

    "circuit_breaker_insulation_resistance": {
        "key": "circuit_breaker_insulation_resistance",
        "name": "Insulation Resistance Test",
        "equipment_type": "Circuit Breaker",
        "description": "Insulation resistance measurement of circuit breaker in open and closed positions.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "cb_make":         "equipment.manufacturer",
            "cb_serial":       "equipment.factory_serial_number",
            "voltage_class_kv":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "cb_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "cb_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "test_voltage_kv",  "label": "Megger Test Voltage", "type": "number", "unit": "kV",  "required": True},
                    {"key": "ambient_temp_c",   "label": "Ambient Temperature", "type": "number", "unit": "°C"},
                    {"key": "humidity_pct",     "label": "Relative Humidity",   "type": "number", "unit": "%"},
                ],
            },
            {
                "title": "IR Readings — CB Open Position",
                "fields": [
                    {
                        "key": "ir_open",
                        "label": "IR (CB Open) in GΩ",
                        "type": "table",
                        "columns": [
                            {"key": "measurement",   "label": "Measurement",    "type": "text"},
                            {"key": "r_phase",       "label": "R Phase (GΩ)",   "type": "number"},
                            {"key": "y_phase",       "label": "Y Phase (GΩ)",   "type": "number"},
                            {"key": "b_phase",       "label": "B Phase (GΩ)",   "type": "number"},
                        ],
                        "default_rows": [
                            {"measurement": "1 min (R60)"},
                            {"measurement": "10 min (R600)"},
                            {"measurement": "PI (R600/R60)"},
                        ],
                    },
                ],
            },
            {
                "title": "IR Readings — CB Closed Position",
                "fields": [
                    {
                        "key": "ir_closed",
                        "label": "IR (CB Closed) in GΩ",
                        "type": "table",
                        "columns": [
                            {"key": "measurement", "label": "Measurement",   "type": "text"},
                            {"key": "r_phase",     "label": "R Phase (GΩ)", "type": "number"},
                            {"key": "y_phase",     "label": "Y Phase (GΩ)", "type": "number"},
                            {"key": "b_phase",     "label": "B Phase (GΩ)", "type": "number"},
                        ],
                        "default_rows": [
                            {"measurement": "Phase to Earth"},
                            {"measurement": "Phase to Phase"},
                        ],
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Conditional"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFC}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "circuit_breaker_sf6_pressure": {
        "key": "circuit_breaker_sf6_pressure",
        "name": "SF6 Gas Pressure Test",
        "equipment_type": "Circuit Breaker",
        "description": "SF6 gas pressure check against rated and minimum operating pressure.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "cb_make":         "equipment.manufacturer",
            "cb_serial":       "equipment.factory_serial_number",
            "voltage_class_kv":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "cb_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "cb_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "rated_pressure_bar",  "label": "Rated Gas Pressure",     "type": "number", "unit": "bar (20°C)"},
                    {"key": "min_op_pressure_bar", "label": "Min Operating Pressure", "type": "number", "unit": "bar"},
                    {"key": "alarm_pressure_bar",  "label": "Alarm Pressure Setting", "type": "number", "unit": "bar"},
                ],
            },
            {
                "title": "Gas Pressure Readings",
                "fields": [
                    {
                        "key": "pressure_readings",
                        "label": "Pressure per Pole",
                        "type": "table",
                        "columns": [
                            {"key": "pole",           "label": "Pole / Chamber",      "type": "text"},
                            {"key": "pressure_bar",   "label": "Measured (bar)",      "type": "number"},
                            {"key": "temp_c",         "label": "Ambient Temp (°C)",   "type": "number"},
                            {"key": "corrected_bar",  "label": "Corrected to 20°C",   "type": "number"},
                            {"key": "result",         "label": "Result",              "type": "dropdown", "options": ["Normal", "Low", "Critical"], "column_evaluation": _EV_NHC},
                        ],
                        "default_rows": [
                            {"pole": "R Phase"},
                            {"pole": "Y Phase"},
                            {"pole": "B Phase"},
                        ],
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "top_up_done",    "label": "Gas Top-up Done",    "type": "boolean"},
                    {"key": "top_up_qty_kg",  "label": "Gas Added",          "type": "number",   "unit": "kg"},
                    {"key": "remarks",        "label": "Remarks",            "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result",     "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Topped Up - Pass"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFTP}},
                    {"key": "tested_by",      "label": "Tested By",          "type": "text",     "required": True},
                ],
            },
        ],
    },

    "circuit_breaker_sf6_purity": {
        "key": "circuit_breaker_sf6_purity",
        "name": "SF6 Gas Purity Test",
        "equipment_type": "Circuit Breaker",
        "description": "SF6 gas purity analysis — moisture, decomposition products, and purity percentage.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "cb_make":         "equipment.manufacturer",
            "cb_serial":       "equipment.factory_serial_number",
            "voltage_class_kv":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "cb_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "cb_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "analyzer_make",   "label": "Analyzer Make",   "type": "text"},
                    {"key": "analyzer_serial", "label": "Analyzer Serial", "type": "text"},
                ],
            },
            {
                "title": "Gas Quality Measurements",
                "fields": [
                    {
                        "key": "purity_readings",
                        "label": "Gas Quality per Pole",
                        "type": "table",
                        "columns": [
                            {"key": "pole",           "label": "Pole",                "type": "text"},
                            {"key": "purity_pct",     "label": "Purity (%)",          "type": "number"},
                            {"key": "moisture_ppm",   "label": "Moisture (ppmv)",     "type": "number"},
                            {"key": "dew_point_c",    "label": "Dew Point (°C)",      "type": "number"},
                            {"key": "so2_ppm",        "label": "SO₂ (ppm)",           "type": "number"},
                            {"key": "result",         "label": "Result",              "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF},
                        ],
                        "default_rows": [
                            {"pole": "R Phase"},
                            {"pole": "Y Phase"},
                            {"pole": "B Phase"},
                        ],
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "gas_replacement_done", "label": "Gas Replacement Done", "type": "boolean"},
                    {"key": "remarks",              "label": "Remarks",              "type": "textarea"},
                    {"key": "overall_result",       "label": "Overall Result",       "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Gas Replaced - Pass"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFGR}},
                    {"key": "tested_by",            "label": "Tested By",            "type": "text",     "required": True},
                ],
            },
        ],
    },

    "circuit_breaker_travel_timing": {
        "key": "circuit_breaker_travel_timing",
        "name": "Travel and Timing Test",
        "equipment_type": "Circuit Breaker",
        "description": "Circuit breaker operating time, travel, and velocity measurements per IEC 62271-100.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "cb_make":         "equipment.manufacturer",
            "cb_serial":       "equipment.factory_serial_number",
            "voltage_class_kv":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "cb_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "cb_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "rated_voltage_dc", "label": "Rated Control Voltage", "type": "number", "unit": "Vdc"},
                    {"key": "analyzer_make",    "label": "Analyzer Make/Model",   "type": "text"},
                ],
            },
            {
                "title": "Opening Operation",
                "fields": [
                    {
                        "key": "opening_times",
                        "label": "Opening Times (ms)",
                        "type": "table",
                        "columns": [
                            {"key": "operation",   "label": "Operation",        "type": "text"},
                            {"key": "r_phase_ms",  "label": "R Phase (ms)",     "type": "number"},
                            {"key": "y_phase_ms",  "label": "Y Phase (ms)",     "type": "number"},
                            {"key": "b_phase_ms",  "label": "B Phase (ms)",     "type": "number"},
                            {"key": "limit_ms",    "label": "Max Limit (ms)",   "type": "number"},
                            {"key": "result",      "label": "Result",           "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF},
                        ],
                        "default_rows": [
                            {"operation": "Opening Time"},
                            {"operation": "Contact Wipe"},
                            {"operation": "Contact Travel (mm)"},
                            {"operation": "Opening Velocity (m/s)"},
                        ],
                    },
                ],
            },
            {
                "title": "Closing Operation",
                "fields": [
                    {
                        "key": "closing_times",
                        "label": "Closing Times (ms)",
                        "type": "table",
                        "columns": [
                            {"key": "operation",   "label": "Operation",        "type": "text"},
                            {"key": "r_phase_ms",  "label": "R Phase (ms)",     "type": "number"},
                            {"key": "y_phase_ms",  "label": "Y Phase (ms)",     "type": "number"},
                            {"key": "b_phase_ms",  "label": "B Phase (ms)",     "type": "number"},
                            {"key": "limit_ms",    "label": "Max Limit (ms)",   "type": "number"},
                            {"key": "result",      "label": "Result",           "type": "dropdown", "options": ["Pass", "Fail"]},
                        ],
                        "default_rows": [
                            {"operation": "Closing Time"},
                            {"operation": "Closing Velocity (m/s)"},
                            {"operation": "Bounce Time (ms)"},
                        ],
                    },
                ],
            },
            {
                "title": "Close-Open (CO) Operation",
                "fields": [
                    {"key": "co_open_time_ms",  "label": "CO — Open Time",     "type": "number", "unit": "ms"},
                    {"key": "co_dead_time_ms",  "label": "CO — Dead Time",     "type": "number", "unit": "ms"},
                    {"key": "co_result",        "label": "CO Result",          "type": "dropdown", "options": ["Pass", "Fail", "Not Tested"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFNT}},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Conditional"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFC}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "circuit_breaker_min_trip_voltage": {
        "key": "circuit_breaker_min_trip_voltage",
        "name": "Minimum Trip Voltage Test",
        "equipment_type": "Circuit Breaker",
        "description": "Determines minimum control voltage at which the CB trips reliably.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "cb_make":         "equipment.manufacturer",
            "cb_serial":       "equipment.factory_serial_number",
            "rated_current_a": "nameplate.rated_current",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "cb_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "cb_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                    {"key": "rated_current_a", "label": "Rated Current", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "rated_control_voltage_v", "label": "Rated Control Voltage", "type": "number", "unit": "V", "required": True},
                ],
            },
            {
                "title": "Trip Coil Test",
                "fields": [
                    {"key": "trip_coil_resistance_ohm",  "label": "Trip Coil Resistance",         "type": "number", "unit": "Ω"},
                    {"key": "min_trip_voltage_v",         "label": "Min Trip Voltage (Actual)",     "type": "number", "unit": "V",  "required": True},
                    {"key": "min_trip_voltage_pct",       "label": "Min Trip Voltage (% of Rated)", "type": "number", "unit": "%"},
                    {"key": "spec_min_pct",               "label": "Specified Minimum (%)",         "type": "number", "unit": "%", "placeholder": "e.g. 70"},
                    {"key": "trip_time_at_min_v_ms",      "label": "Trip Time at Min Voltage",      "type": "number", "unit": "ms"},
                    {"key": "close_coil_resistance_ohm",  "label": "Close Coil Resistance",         "type": "number", "unit": "Ω"},
                    {"key": "min_close_voltage_v",        "label": "Min Close Voltage (Actual)",    "type": "number", "unit": "V"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PF}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "circuit_breaker_maintenance": {
        "key": "circuit_breaker_maintenance",
        "name": "Circuit Breaker Preventive Maintenance",
        "equipment_type": "Circuit Breaker",
        "description": "Routine and major preventive maintenance checklist for circuit breakers.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"station_name": "equipment.department_name", "bay_number": "equipment.bay_number", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number", "voltage_class": "equipment.voltage_class"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                {"key": "voltage_class", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Maintenance Metadata",
                "fields": [
                    {"key": "maintenance_date",    "label": "Date of Maintenance",           "type": "date",   "required": True},
                    {"key": "maintenance_time",    "label": "Time",                           "type": "text",   "placeholder": "HH:MM"},
                    {"key": "ambient_temp_c",      "label": "Ambient Temperature",            "type": "number", "unit": "°C"},
                    {"key": "humidity_pct",        "label": "Relative Humidity",              "type": "number", "unit": "%"},
                    {"key": "maintenance_officer", "label": "Name and Designation of Officer","type": "text",   "required": True},
                    {"key": "witness_officer",     "label": "Name of Witnessing Officer",     "type": "text"},
                    {"key": "ops_count_at_maint",  "label": "Operations Count at Maintenance","type": "number"},
                ],
            },
            {
                "title": "Maintenance Checklist",
                "fields": [
                    {"key": "permit_to_work",         "label": "Permit to Work obtained",                 "type": "checkbox", "required": True},
                    {"key": "lockout_tagout",          "label": "Lockout / Tagout applied",                "type": "checkbox", "required": True},
                    {"key": "earth_applied",           "label": "Earth connections applied",               "type": "checkbox", "required": True},
                    {"key": "sf6_pressure_checked",    "label": "SF6 gas pressure checked",                "type": "checkbox", "required": True},
                    {"key": "general_cleaning",        "label": "General cleaning completed",              "type": "checkbox", "required": True},
                    {"key": "mechanism_lubricated",    "label": "Operating mechanism lubricated",          "type": "checkbox"},
                    {"key": "trip_close_ops_checked",  "label": "Trip / close operations verified",        "type": "dropdown", "options": ["Pass", "Fail", "N/A"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFNA}},
                    {"key": "heater_working",          "label": "Anti-condensation heater working",        "type": "checkbox"},
                    {"key": "control_cables_ok",       "label": "Control cables and connections intact",   "type": "checkbox"},
                    {"key": "earthing_ok",             "label": "Earthing connections intact",             "type": "checkbox"},
                    {"key": "no_corrosion",            "label": "No corrosion / physical damage observed", "type": "checkbox"},
                    {"key": "bushing_insulators_clean","label": "Bushing insulators cleaned",              "type": "checkbox"},
                    {"key": "observations",            "label": "Observations",                            "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Satisfactory", "Unsatisfactory", "Action Required"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_SAT}},
                    {"key": "next_maint_due", "label": "Next Maintenance Due", "type": "date"},
                    {"key": "maintained_by",  "label": "Maintained By",  "type": "text",     "required": True},
                ],
            },
        ],
    },

    "circuit_breaker_inspection": {
        "key": "circuit_breaker_inspection",
        "name": "Circuit Breaker Annual Inspection",
        "equipment_type": "Circuit Breaker",
        "description": "Annual inspection checklist for circuit breakers — safety, civil, fire, and documentation.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"station_name": "equipment.department_name", "bay_number": "equipment.bay_number", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number", "voltage_class": "equipment.voltage_class"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                {"key": "voltage_class", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Inspection Details",
                "fields": [
                    {"key": "inspection_date",    "label": "Date of Inspection",  "type": "date", "required": True},
                    {"key": "inspection_type",    "label": "Inspection Category", "type": "dropdown", "required": True,
                     "options": ["Electrical Safety", "Civil", "Fire Safety", "Documentation", "Environmental", "General Maintenance"]},
                    {"key": "inspector_name",     "label": "Inspector Name",      "type": "text", "required": True},
                ],
            },
            {
                "title": "Inspection Checklist",
                "fields": [
                    {"key": "physical_condition_ok",   "label": "Physical condition satisfactory",         "type": "checkbox"},
                    {"key": "labelling_ok",             "label": "Equipment labelling complete and legible", "type": "checkbox"},
                    {"key": "earthing_ok",              "label": "Earthing and bonding intact",              "type": "checkbox"},
                    {"key": "safety_clearances_ok",     "label": "Safety clearances maintained",             "type": "checkbox"},
                    {"key": "fire_extinguisher_ok",     "label": "Fire extinguisher in place and valid",     "type": "checkbox"},
                    {"key": "documents_updated",        "label": "Test and maintenance records up to date",  "type": "checkbox"},
                    {"key": "observations",             "label": "Observations / Non-conformances",          "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "compliance_status", "label": "Compliance Status", "type": "dropdown", "required": True, "options": ["Compliant", "Non-Compliant", "Partial"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_COMPLY}},
                    {"key": "action_required",   "label": "Action Required",   "type": "textarea"},
                    {"key": "inspected_by",      "label": "Inspected By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    # ════════════════════════════════════════════════════════════════════════════
    # SURGE ARRESTOR TEMPLATES
    # ════════════════════════════════════════════════════════════════════════════

    "surge_arrestor_ir_leakage": {
        "key": "surge_arrestor_ir_leakage",
        "name": "Insulation Resistance / Leakage Current Test",
        "equipment_type": "Surge Arrestor",
        "description": "Insulation resistance and leakage current measurement of surge arrestors.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "sa_make":         "equipment.manufacturer",
            "sa_serial":       "equipment.factory_serial_number",
            "voltage_class_kv":"equipment.voltage_class",
            "rated_voltage_kv":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "sa_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "sa_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                    {"key": "rated_voltage_kv", "label": "Rated Voltage (kV)", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "test_voltage_kv", "label": "Megger Test Voltage", "type": "number", "unit": "kV", "required": True},
                    {"key": "ambient_temp_c",  "label": "Ambient Temperature", "type": "number", "unit": "°C"},
                ],
            },
            {
                "title": "IR and Leakage Current Readings",
                "fields": [
                    {
                        "key": "ir_readings",
                        "label": "Per Phase Readings",
                        "type": "table",
                        "columns": [
                            {"key": "phase",          "label": "Phase",                "type": "text"},
                            {"key": "ir_mohm",        "label": "IR (MΩ)",             "type": "number"},
                            {"key": "leakage_ua",     "label": "Leakage Current (µA)", "type": "number"},
                            {"key": "prev_leakage_ua","label": "Previous Reading (µA)","type": "number"},
                            {"key": "deviation_pct",  "label": "Deviation (%)",        "type": "number"},
                            {"key": "result",         "label": "Result",               "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF},
                        ],
                        "default_rows": [
                            {"phase": "R Phase"},
                            {"phase": "Y Phase"},
                            {"phase": "B Phase"},
                        ],
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Conditional"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFC}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "surge_arrestor_vi_characteristic": {
        "key": "surge_arrestor_vi_characteristic",
        "name": "V-I Characteristic Test",
        "equipment_type": "Surge Arrestor",
        "description": "Voltage-current characteristic test to verify arrestor clamp voltage and knee-point.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "sa_make":         "equipment.manufacturer",
            "sa_serial":       "equipment.factory_serial_number",
            "voltage_class_kv":"equipment.voltage_class",
            "rated_voltage_kv":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "sa_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "sa_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                    {"key": "rated_voltage_kv", "label": "Rated Voltage (kV)", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "nominal_discharge_ka", "label": "Nominal Discharge Current", "type": "number", "unit": "kA"},
                    {"key": "test_equipment",        "label": "Test Equipment Used",       "type": "text"},
                ],
            },
            {
                "title": "V-I Characteristic Readings",
                "fields": [
                    {
                        "key": "vi_curve",
                        "label": "V-I Curve Points",
                        "type": "table",
                        "columns": [
                            {"key": "point",      "label": "Point",          "type": "text"},
                            {"key": "voltage_kv", "label": "Voltage (kV)",   "type": "number"},
                            {"key": "current_a",  "label": "Current (A)",    "type": "number"},
                            {"key": "phase",      "label": "Phase",          "type": "dropdown", "options": ["R", "Y", "B", "All"]},
                        ],
                        "default_rows": [
                            {"point": "Point 1"},
                            {"point": "Point 2"},
                            {"point": "Point 3 (Knee)"},
                            {"point": "Point 4"},
                            {"point": "Point 5"},
                        ],
                    },
                    {"key": "residual_voltage_kv",  "label": "Residual Voltage at 8/20µs", "type": "number", "unit": "kV"},
                    {"key": "ref_voltage_kv",        "label": "Reference Voltage (1mA)",    "type": "number", "unit": "kV"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Conditional"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFC}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "surge_arrestor_power_freq_withstand": {
        "key": "surge_arrestor_power_freq_withstand",
        "name": "Power Frequency Voltage Withstand Test",
        "equipment_type": "Surge Arrestor",
        "description": "Power frequency voltage withstand test per IEC 60099-4.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":    "equipment.department_name",
            "bay_number":      "equipment.bay_number",
            "sa_make":         "equipment.manufacturer",
            "sa_serial":       "equipment.factory_serial_number",
            "voltage_class_kv":"equipment.voltage_class",
            "rated_voltage_kv":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                    {"key": "sa_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "sa_serial", "label": "Serial Number", "type": "readonly"},
                    {"key": "voltage_class_kv", "label": "Voltage Class", "type": "readonly"},
                    {"key": "rated_voltage_kv", "label": "Rated Voltage (kV)", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "test_equipment", "label": "Test Equipment Used", "type": "text"},
                ],
            },
            {
                "title": "Withstand Test",
                "fields": [
                    {
                        "key": "withstand_readings",
                        "label": "Per Phase Withstand Test",
                        "type": "table",
                        "columns": [
                            {"key": "phase",             "label": "Phase",                  "type": "text"},
                            {"key": "test_voltage_kv",   "label": "Test Voltage (kVrms)",    "type": "number"},
                            {"key": "duration_sec",      "label": "Duration (s)",            "type": "number"},
                            {"key": "flashover",         "label": "Flashover / Breakdown",   "type": "dropdown", "options": ["No", "Yes"]},
                            {"key": "result",            "label": "Result",                  "type": "dropdown", "options": ["Pass", "Fail"], "column_evaluation": _EV_PF},
                        ],
                        "default_rows": [
                            {"phase": "R Phase"},
                            {"phase": "Y Phase"},
                            {"phase": "B Phase"},
                        ],
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PF}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "surge_arrestor_maintenance": {
        "key": "surge_arrestor_maintenance",
        "name": "Surge Arrestor Maintenance",
        "equipment_type": "Surge Arrestor",
        "description": "Routine visual inspection and major maintenance checklist for surge arrestors.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"station_name": "equipment.department_name", "bay_number": "equipment.bay_number", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number", "voltage_class": "equipment.voltage_class"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                {"key": "voltage_class", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Maintenance Metadata",
                "fields": [
                    {"key": "maintenance_date",    "label": "Date of Maintenance",           "type": "date", "required": True},
                    {"key": "maintenance_type",    "label": "Maintenance Type",               "type": "dropdown", "options": ["Routine Visual Inspection", "LA Major Maintenance"]},
                    {"key": "ambient_temp_c",      "label": "Ambient Temperature",            "type": "number", "unit": "°C"},
                    {"key": "maintenance_officer", "label": "Name and Designation of Officer","type": "text",   "required": True},
                ],
            },
            {
                "title": "Visual Inspection Checklist",
                "fields": [
                    {"key": "no_cracks",          "label": "No cracks or chips on housing / insulators",       "type": "checkbox"},
                    {"key": "no_contamination",   "label": "No contamination / pollution deposits",            "type": "checkbox"},
                    {"key": "insulator_clean",    "label": "Insulator surface cleaned",                        "type": "checkbox"},
                    {"key": "connections_tight",  "label": "All connections and clamps tight",                 "type": "checkbox"},
                    {"key": "earthing_ok",        "label": "Earthing connections intact and tight",            "type": "checkbox"},
                    {"key": "counter_reading",    "label": "Surge Counter Reading",                            "type": "number"},
                    {"key": "prev_counter",       "label": "Previous Counter Reading",                         "type": "number"},
                    {"key": "operations_since",   "label": "Operations Since Last Inspection",                 "type": "number"},
                    {"key": "no_physical_damage", "label": "No physical damage observed",                      "type": "checkbox"},
                    {"key": "observations",       "label": "Observations",                                     "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Satisfactory", "Unsatisfactory", "Action Required"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_SAT}},
                    {"key": "maintained_by",  "label": "Maintained By",  "type": "text",     "required": True},
                ],
            },
        ],
    },

    "surge_arrestor_inspection": {
        "key": "surge_arrestor_inspection",
        "name": "Surge Arrestor Annual Inspection",
        "equipment_type": "Surge Arrestor",
        "description": "Annual inspection checklist for surge arrestors — safety, documentation, and general maintenance.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"station_name": "equipment.department_name", "bay_number": "equipment.bay_number", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number", "voltage_class": "equipment.voltage_class"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                {"key": "bay_number", "label": "Bay Number", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                {"key": "voltage_class", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Inspection Details",
                "fields": [
                    {"key": "inspection_date",  "label": "Date of Inspection",  "type": "date", "required": True},
                    {"key": "inspection_type",  "label": "Inspection Category", "type": "dropdown", "required": True,
                     "options": ["Electrical Safety", "General Maintenance", "Documentation"]},
                    {"key": "inspector_name",   "label": "Inspector Name",      "type": "text", "required": True},
                ],
            },
            {
                "title": "Inspection Checklist",
                "fields": [
                    {"key": "labelling_ok",     "label": "Equipment labelling complete and legible",    "type": "checkbox"},
                    {"key": "earthing_ok",       "label": "Earthing and bonding intact",                 "type": "checkbox"},
                    {"key": "physical_ok",       "label": "No physical damage or contamination",         "type": "checkbox"},
                    {"key": "docs_updated",      "label": "Test and maintenance records up to date",     "type": "checkbox"},
                    {"key": "observations",      "label": "Observations / Non-conformances",             "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "compliance_status", "label": "Compliance Status", "type": "dropdown", "required": True, "options": ["Compliant", "Non-Compliant", "Partial"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_COMPLY}},
                    {"key": "action_required",   "label": "Action Required",   "type": "textarea"},
                    {"key": "inspected_by",      "label": "Inspected By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    # ════════════════════════════════════════════════════════════════════════════
    # BATTERY SET TEMPLATES
    # ════════════════════════════════════════════════════════════════════════════

    "battery_specific_gravity": {
        "key": "battery_specific_gravity",
        "name": "Specific Gravity Check",
        "equipment_type": "Battery Set",
        "description": "Cell-wise specific gravity measurement to assess electrolyte condition.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":   "equipment.department_name",
            "battery_make":   "equipment.manufacturer",
            "rated_voltage_v":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "battery_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "rated_voltage_v", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "battery_id",         "label": "Battery Set ID",          "type": "text"},
                    {"key": "battery_type",        "label": "Battery Type",            "type": "dropdown", "options": ["Lead Acid", "VRLA", "Ni-Cd", "Lithium Ion"]},
                    {"key": "num_cells",           "label": "Number of Cells",         "type": "number"},
                    {"key": "hydrometer_make",     "label": "Hydrometer Make",         "type": "text"},
                    {"key": "electrolyte_temp_c",  "label": "Electrolyte Temperature", "type": "number", "unit": "°C"},
                ],
            },
            {
                "title": "Specific Gravity Readings",
                "fields": [
                    {
                        "key": "sg_readings",
                        "label": "Cell-wise Specific Gravity",
                        "type": "table",
                        "columns": [
                            {"key": "cell_no",      "label": "Cell No.",               "type": "text"},
                            {"key": "sg_value",     "label": "SG Reading",             "type": "number"},
                            {"key": "sg_corrected", "label": "Temp-Corrected SG",      "type": "number"},
                            {"key": "condition",    "label": "Condition",              "type": "dropdown", "options": ["Good", "Low", "Critical"], "column_evaluation": {"Good": "NORMAL", "Low": "ALERT", "Critical": "CRITICAL"}},
                        ],
                        "default_rows": [
                            {"cell_no": "Cell 1"}, {"cell_no": "Cell 2"}, {"cell_no": "Cell 3"},
                            {"cell_no": "Cell 4"}, {"cell_no": "Cell 5"}, {"cell_no": "Cell 6"},
                        ],
                    },
                    {"key": "avg_sg",           "label": "Average SG",            "type": "number"},
                    {"key": "min_sg",           "label": "Minimum SG (worst cell)","type": "number"},
                    {"key": "rated_sg",         "label": "Rated SG (fully charged)","type": "number"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "water_added",    "label": "Distilled Water Added",  "type": "boolean"},
                    {"key": "remarks",        "label": "Remarks",                "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result",         "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Monitor"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFM}},
                    {"key": "tested_by",      "label": "Tested By",              "type": "text",     "required": True},
                ],
            },
        ],
    },

    "battery_float_voltage": {
        "key": "battery_float_voltage",
        "name": "Float Voltage per Cell",
        "equipment_type": "Battery Set",
        "description": "Measurement of individual cell float voltages under normal charging conditions.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name": "equipment.department_name",
            "battery_make": "equipment.manufacturer",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "battery_make", "label": "Manufacturer", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "battery_id",       "label": "Battery Set ID",          "type": "text"},
                    {"key": "num_cells",         "label": "Number of Cells",         "type": "number"},
                    {"key": "charger_output_v",  "label": "Charger Output Voltage",  "type": "number", "unit": "V"},
                    {"key": "rated_float_v",     "label": "Rated Float Voltage/Cell","type": "number", "unit": "V"},
                    {"key": "multimeter_make",   "label": "Multimeter Make",         "type": "text"},
                ],
            },
            {
                "title": "Cell Voltage Readings",
                "fields": [
                    {
                        "key": "voltage_readings",
                        "label": "Per-Cell Float Voltage",
                        "type": "table",
                        "columns": [
                            {"key": "cell_no",  "label": "Cell No.",         "type": "text"},
                            {"key": "voltage_v","label": "Voltage (V)",      "type": "number"},
                            {"key": "deviation","label": "Deviation from Rated (V)","type": "number"},
                            {"key": "condition","label": "Condition",        "type": "dropdown", "options": ["Normal", "High", "Low"], "column_evaluation": _EV_NHC},
                        ],
                        "default_rows": [
                            {"cell_no": "Cell 1"}, {"cell_no": "Cell 2"}, {"cell_no": "Cell 3"},
                            {"cell_no": "Cell 4"}, {"cell_no": "Cell 5"}, {"cell_no": "Cell 6"},
                        ],
                    },
                    {"key": "total_bank_voltage_v", "label": "Total Bank Voltage",   "type": "number", "unit": "V"},
                    {"key": "avg_cell_voltage_v",   "label": "Average Cell Voltage",  "type": "number", "unit": "V"},
                    {"key": "min_cell_voltage_v",   "label": "Minimum Cell Voltage",  "type": "number", "unit": "V"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Monitor"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFM}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "battery_discharge_capacity": {
        "key": "battery_discharge_capacity",
        "name": "Discharge / Capacity Test",
        "equipment_type": "Battery Set",
        "description": "Battery discharge test to verify rated capacity per IEEE 450.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name": "equipment.department_name",
            "battery_make": "equipment.manufacturer",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "battery_make", "label": "Manufacturer", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "battery_id",          "label": "Battery Set ID",          "type": "text"},
                    {"key": "battery_type",        "label": "Battery Type",            "type": "dropdown", "options": ["Lead Acid", "VRLA", "Ni-Cd", "Lithium Ion"]},
                    {"key": "rated_capacity_ah",   "label": "Rated Capacity",          "type": "number", "unit": "Ah", "required": True},
                    {"key": "discharge_rate_hr",   "label": "Discharge Rate",          "type": "number", "unit": "hr (e.g. 10)"},
                    {"key": "discharge_current_a", "label": "Discharge Current",       "type": "number", "unit": "A",  "required": True},
                    {"key": "initial_voltage_v",   "label": "Initial Voltage",         "type": "number", "unit": "V",  "required": True},
                    {"key": "cutoff_voltage_v",    "label": "End-of-Discharge Voltage","type": "number", "unit": "V"},
                ],
            },
            {
                "title": "Discharge Data",
                "fields": [
                    {
                        "key": "discharge_log",
                        "label": "Periodic Voltage Log",
                        "type": "table",
                        "columns": [
                            {"key": "time_hr",    "label": "Time (hr)",         "type": "number"},
                            {"key": "voltage_v",  "label": "Bank Voltage (V)",  "type": "number"},
                            {"key": "current_a",  "label": "Current (A)",       "type": "number"},
                            {"key": "temp_c",     "label": "Temp (°C)",         "type": "number"},
                        ],
                        "default_rows": [
                            {"time_hr": "0"}, {"time_hr": "1"}, {"time_hr": "2"},
                            {"time_hr": "4"}, {"time_hr": "6"}, {"time_hr": "8"}, {"time_hr": "10"},
                        ],
                    },
                    {"key": "actual_capacity_ah",  "label": "Actual Capacity Achieved", "type": "number", "unit": "Ah"},
                    {"key": "capacity_pct",         "label": "Capacity (% of Rated)",    "type": "number", "unit": "%"},
                    {"key": "discharge_duration_hr","label": "Total Discharge Duration", "type": "number", "unit": "hr"},
                    {"key": "end_voltage_v",        "label": "End Voltage at Cutoff",    "type": "number", "unit": "V"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Marginal"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFM}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "battery_electrolyte_level": {
        "key": "battery_electrolyte_level",
        "name": "Electrolyte Level Check",
        "equipment_type": "Battery Set",
        "description": "Cell-wise electrolyte level inspection and top-up record.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name": "equipment.department_name",
            "battery_make": "equipment.manufacturer",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "battery_make", "label": "Manufacturer", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "battery_id", "label": "Battery Set ID",  "type": "text"},
                    {"key": "num_cells",  "label": "Number of Cells", "type": "number"},
                ],
            },
            {
                "title": "Electrolyte Level Readings",
                "fields": [
                    {
                        "key": "level_readings",
                        "label": "Per-Cell Electrolyte Level",
                        "type": "table",
                        "columns": [
                            {"key": "cell_no",     "label": "Cell No.",      "type": "text"},
                            {"key": "level",       "label": "Level",         "type": "dropdown", "options": ["Normal", "Low", "High", "Critical Low"], "column_evaluation": _EV_NHC},
                            {"key": "water_added_ml", "label": "Water Added (ml)", "type": "number"},
                            {"key": "remarks",     "label": "Remarks",       "type": "text"},
                        ],
                        "default_rows": [
                            {"cell_no": "Cell 1"}, {"cell_no": "Cell 2"}, {"cell_no": "Cell 3"},
                            {"cell_no": "Cell 4"}, {"cell_no": "Cell 5"}, {"cell_no": "Cell 6"},
                        ],
                    },
                    {"key": "total_water_added_ml", "label": "Total Distilled Water Added", "type": "number", "unit": "ml"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Normal", "Low — Topped Up", "Critical — Action Required"], "dropdown_evaluation": {"enabled": True, "value_severities": {"Normal": "NORMAL", "Low — Topped Up": "ALERT", "Critical — Action Required": "CRITICAL"}}},
                    {"key": "checked_by",     "label": "Checked By",     "type": "text",     "required": True},
                ],
            },
        ],
    },

    "battery_terminal_voltage": {
        "key": "battery_terminal_voltage",
        "name": "Terminal Voltage Measurement",
        "equipment_type": "Battery Set",
        "description": "Overall bank terminal voltage and individual cell voltage under float / standby conditions.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {
            "station_name":   "equipment.department_name",
            "battery_make":   "equipment.manufacturer",
            "rated_voltage_v":"equipment.voltage_class",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                    {"key": "battery_make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "rated_voltage_v", "label": "Voltage Class", "type": "readonly"},
                ],
            },
            {
                "title": "Equipment Details",
                "fields": [
                    {"key": "battery_id",     "label": "Battery Set ID",  "type": "text"},
                    {"key": "num_cells",      "label": "Number of Cells", "type": "number"},
                    {"key": "multimeter_make","label": "Multimeter Make", "type": "text"},
                    {"key": "charger_status", "label": "Charger Status",  "type": "dropdown", "options": ["Float Charge", "Boost Charge", "Off / Standalone"]},
                ],
            },
            {
                "title": "Terminal Voltage",
                "fields": [
                    {"key": "bank_terminal_v",  "label": "Bank Terminal Voltage",    "type": "number", "unit": "V",  "required": True},
                    {"key": "pos_terminal_v",   "label": "Positive Terminal Voltage", "type": "number", "unit": "V"},
                    {"key": "neg_terminal_v",   "label": "Negative Terminal Voltage", "type": "number", "unit": "V"},
                    {
                        "key": "cell_voltages",
                        "label": "Individual Cell Voltages",
                        "type": "table",
                        "columns": [
                            {"key": "cell_no",   "label": "Cell No.",    "type": "text"},
                            {"key": "voltage_v", "label": "Voltage (V)", "type": "number"},
                            {"key": "condition", "label": "Condition",   "type": "dropdown", "options": ["Normal", "High", "Low"], "column_evaluation": _EV_NHC},
                        ],
                        "default_rows": [
                            {"cell_no": "Cell 1"}, {"cell_no": "Cell 2"}, {"cell_no": "Cell 3"},
                            {"cell_no": "Cell 4"}, {"cell_no": "Cell 5"}, {"cell_no": "Cell 6"},
                        ],
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "remarks",        "label": "Remarks",        "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Pass", "Fail", "Monitor"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_PFM}},
                    {"key": "tested_by",      "label": "Tested By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "battery_maintenance": {
        "key": "battery_maintenance",
        "name": "Battery Set Routine Maintenance",
        "equipment_type": "Battery Set",
        "description": "Routine and major maintenance checklist for battery sets.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"station_name": "equipment.department_name", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Maintenance Metadata",
                "fields": [
                    {"key": "maintenance_date",    "label": "Date of Maintenance",            "type": "date",     "required": True},
                    {"key": "maintenance_type",    "label": "Maintenance Type",                "type": "dropdown", "options": ["Routine Battery Maintenance", "Battery Bank Major Maintenance"]},
                    {"key": "ambient_temp_c",      "label": "Ambient Temperature",             "type": "number",   "unit": "°C"},
                    {"key": "maintenance_officer", "label": "Name and Designation of Officer", "type": "text",     "required": True},
                ],
            },
            {
                "title": "Maintenance Checklist",
                "fields": [
                    {"key": "permit_to_work",       "label": "Permit to Work obtained",                "type": "checkbox", "required": True},
                    {"key": "ppe_used",              "label": "Appropriate PPE used (acid-resistant)",  "type": "checkbox", "required": True},
                    {"key": "terminal_cleaning",    "label": "Terminals cleaned and greased",           "type": "checkbox"},
                    {"key": "connections_tightened","label": "All connections tightened",               "type": "checkbox"},
                    {"key": "vent_plugs_ok",        "label": "Vent plugs / caps clean and intact",      "type": "checkbox"},
                    {"key": "tray_cleaned",         "label": "Battery tray / room cleaned",             "type": "checkbox"},
                    {"key": "earthing_ok",          "label": "Earthing connections checked",            "type": "checkbox"},
                    {"key": "charger_output_ok",    "label": "Charger output voltage checked",          "type": "dropdown", "options": ["Normal", "High", "Low", "Not Checked"], "dropdown_evaluation": {"enabled": True, "value_severities": {"Normal": "NORMAL", "High": "ALERT", "Low": "ALERT", "Not Checked": "NORMAL"}}},
                    {"key": "electrolyte_checked",  "label": "Electrolyte level checked",               "type": "checkbox"},
                    {"key": "water_added",          "label": "Distilled water added if required",       "type": "checkbox"},
                    {"key": "sg_checked",           "label": "Specific gravity checked",                "type": "checkbox"},
                    {"key": "no_cracks",            "label": "No cracks or bulging observed",           "type": "checkbox"},
                    {"key": "observations",         "label": "Observations",                            "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Satisfactory", "Unsatisfactory", "Action Required"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_SAT}},
                    {"key": "maintained_by",  "label": "Maintained By",  "type": "text",     "required": True},
                ],
            },
        ],
    },

    "battery_inspection": {
        "key": "battery_inspection",
        "name": "Battery Set Annual Inspection",
        "equipment_type": "Battery Set",
        "description": "Annual inspection checklist for battery sets — safety, documentation, and environmental.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"station_name": "equipment.department_name", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Inspection Details",
                "fields": [
                    {"key": "battery_id",      "label": "Battery Set ID",     "type": "text"},
                    {"key": "inspection_date", "label": "Date of Inspection",  "type": "date", "required": True},
                    {"key": "inspection_type", "label": "Inspection Category", "type": "dropdown", "required": True,
                     "options": ["Electrical Safety", "Environmental", "General Maintenance", "Documentation"]},
                    {"key": "inspector_name",  "label": "Inspector Name",      "type": "text", "required": True},
                ],
            },
            {
                "title": "Inspection Checklist",
                "fields": [
                    {"key": "acid_spill_ok",    "label": "No acid spills or leakage",               "type": "checkbox"},
                    {"key": "ventilation_ok",   "label": "Room ventilation adequate",               "type": "checkbox"},
                    {"key": "earthing_ok",       "label": "Earthing and bonding intact",             "type": "checkbox"},
                    {"key": "labelling_ok",      "label": "Equipment labelling complete",            "type": "checkbox"},
                    {"key": "eyewash_ok",        "label": "Eyewash station and PPE available",       "type": "checkbox"},
                    {"key": "docs_updated",      "label": "Test and maintenance records up to date", "type": "checkbox"},
                    {"key": "observations",      "label": "Observations / Non-conformances",         "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "compliance_status", "label": "Compliance Status", "type": "dropdown", "required": True, "options": ["Compliant", "Non-Compliant", "Partial"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_COMPLY}},
                    {"key": "action_required",   "label": "Action Required",   "type": "textarea"},
                    {"key": "inspected_by",      "label": "Inspected By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    # ════════════════════════════════════════════════════════════════════════════
    # PROTECTION RELAY & ETM INSPECTION TEMPLATES
    # ════════════════════════════════════════════════════════════════════════════

    "protection_relay_inspection": {
        "key": "protection_relay_inspection",
        "name": "Protection Relay Annual Inspection",
        "equipment_type": "Protection Relay",
        "description": "Annual inspection checklist for protection relays — safety, documentation, and general maintenance.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"station_name": "equipment.department_name", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Inspection Details",
                "fields": [
                    {"key": "panel_id",        "label": "Panel / Bay ID",     "type": "text"},
                    {"key": "inspection_date", "label": "Date of Inspection",  "type": "date", "required": True},
                    {"key": "inspection_type", "label": "Inspection Category", "type": "dropdown", "required": True,
                     "options": ["Electrical Safety", "General Maintenance", "Documentation"]},
                    {"key": "inspector_name",  "label": "Inspector Name",      "type": "text", "required": True},
                ],
            },
            {
                "title": "Inspection Checklist",
                "fields": [
                    {"key": "panel_clean",        "label": "Panel interior clean and free of dust",   "type": "checkbox"},
                    {"key": "connections_ok",     "label": "All terminal connections tight",          "type": "checkbox"},
                    {"key": "indicators_ok",      "label": "LED indicators / annunciations healthy",  "type": "checkbox"},
                    {"key": "settings_verified",  "label": "Relay settings verified against record",  "type": "checkbox"},
                    {"key": "earthing_ok",        "label": "Panel earthing intact",                   "type": "checkbox"},
                    {"key": "docs_updated",       "label": "Settings record and test log up to date", "type": "checkbox"},
                    {"key": "observations",       "label": "Observations / Non-conformances",         "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "compliance_status", "label": "Compliance Status", "type": "dropdown", "required": True, "options": ["Compliant", "Non-Compliant", "Partial"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_COMPLY}},
                    {"key": "action_required",   "label": "Action Required",   "type": "textarea"},
                    {"key": "inspected_by",      "label": "Inspected By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    "etm_inspection": {
        "key": "etm_inspection",
        "name": "Electronic Tri-vector Meter Annual Inspection",
        "equipment_type": "Electronic Tri-vector Meter",
        "description": "Annual inspection checklist for electronic tri-vector meters.",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"station_name": "equipment.department_name", "manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "station_name", "label": "Station / Substation", "type": "readonly"},
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Inspection Details",
                "fields": [
                    {"key": "feeder_id",       "label": "Feeder / Bay ID",    "type": "text"},
                    {"key": "inspection_date", "label": "Date of Inspection",  "type": "date", "required": True},
                    {"key": "inspection_type", "label": "Inspection Category", "type": "dropdown", "required": True,
                     "options": ["Electrical Safety", "General Maintenance", "Documentation"]},
                    {"key": "inspector_name",  "label": "Inspector Name",      "type": "text", "required": True},
                ],
            },
            {
                "title": "Inspection Checklist",
                "fields": [
                    {"key": "display_ok",       "label": "Meter display functional and readable",      "type": "checkbox"},
                    {"key": "seals_intact",     "label": "Meter seals intact (tamper-evident)",        "type": "checkbox"},
                    {"key": "connections_ok",   "label": "CT / PT connections tight",                  "type": "checkbox"},
                    {"key": "reading_plausible","label": "Meter reading plausible (no anomalies)",     "type": "checkbox"},
                    {"key": "earthing_ok",      "label": "Earthing and bonding intact",                "type": "checkbox"},
                    {"key": "calib_valid",      "label": "Calibration certificate valid",              "type": "checkbox"},
                    {"key": "docs_updated",     "label": "Test and calibration records up to date",    "type": "checkbox"},
                    {"key": "observations",     "label": "Observations / Non-conformances",            "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "compliance_status", "label": "Compliance Status", "type": "dropdown", "required": True, "options": ["Compliant", "Non-Compliant", "Partial"], "dropdown_evaluation": {"enabled": True, "value_severities": _EV_COMPLY}},
                    {"key": "action_required",   "label": "Action Required",   "type": "textarea"},
                    {"key": "inspected_by",      "label": "Inspected By",      "type": "text",     "required": True},
                ],
            },
        ],
    },

    # ────────────────────────────────────────────────────────────
    # Generic Equipment Templates (for new equipment types)
    # ────────────────────────────────────────────────────────────

    "generic_equipment_test": {
        "key": "generic_equipment_test",
        "name": "Generic Equipment Test",
        "equipment_type": "Generic",
        "description": "Generic test template for equipment testing",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "test_date", "label": "Test Date", "type": "date", "required": True},
                    {"key": "test_type", "label": "Test Type", "type": "text", "required": True},
                    {"key": "test_standard", "label": "Test Standard / Procedure", "type": "text"},
                    {"key": "tested_by", "label": "Tested By", "type": "text", "required": True},
                    {"key": "witnessed_by", "label": "Witnessed By", "type": "text"},
                ],
            },
            {
                "title": "Test Parameters",
                "fields": [
                    {"key": "ambient_temp", "label": "Ambient Temperature", "type": "number", "unit": "°C"},
                    {"key": "humidity", "label": "Relative Humidity", "type": "number", "unit": "%"},
                    {"key": "test_equipment", "label": "Test Equipment Used", "type": "textarea"},
                ],
            },
            {
                "title": "Test Results",
                "fields": [
                    {"key": "parameter_1", "label": "Parameter 1", "type": "text"},
                    {"key": "value_1", "label": "Value 1", "type": "text"},
                    {"key": "parameter_2", "label": "Parameter 2", "type": "text"},
                    {"key": "value_2", "label": "Value 2", "type": "text"},
                    {"key": "parameter_3", "label": "Parameter 3", "type": "text"},
                    {"key": "value_3", "label": "Value 3", "type": "text"},
                    {"key": "additional_results", "label": "Additional Results / Measurements", "type": "textarea"},
                ],
            },
            {
                "title": "Assessment",
                "fields": [
                    {"key": "observations", "label": "Observations", "type": "textarea"},
                    {"key": "defects_found", "label": "Defects / Issues Found", "type": "textarea"},
                    {"key": "recommendations", "label": "Recommendations", "type": "textarea"},
                    {"key": "test_result", "label": "Overall Test Result", "type": "dropdown", "required": True,
                     "options": ["Pass", "Fail", "Conditional", "Retest Required"],
                     "dropdown_evaluation": {"enabled": True, "value_severities": {"Pass": "NORMAL", "Fail": "CRITICAL", "Conditional": "ALERT", "Retest Required": "ALERT"}}},
                ],
            },
        ],
    },

    "generic_equipment_maintenance": {
        "key": "generic_equipment_maintenance",
        "name": "Generic Equipment Maintenance",
        "equipment_type": "Generic",
        "description": "Generic maintenance template for equipment maintenance activities",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Maintenance Information",
                "fields": [
                    {"key": "maintenance_date", "label": "Maintenance Date", "type": "date", "required": True},
                    {"key": "maintenance_type", "label": "Maintenance Type", "type": "dropdown", "required": True,
                     "options": ["Preventive", "Corrective", "Predictive", "Emergency"]},
                    {"key": "work_order_no", "label": "Work Order Number", "type": "text"},
                    {"key": "performed_by", "label": "Performed By", "type": "text", "required": True},
                    {"key": "supervised_by", "label": "Supervised By", "type": "text"},
                ],
            },
            {
                "title": "Work Performed",
                "fields": [
                    {"key": "cleaning_done", "label": "Cleaning performed", "type": "checkbox"},
                    {"key": "lubrication_done", "label": "Lubrication performed", "type": "checkbox"},
                    {"key": "adjustment_done", "label": "Adjustments / calibration performed", "type": "checkbox"},
                    {"key": "parts_replaced", "label": "Parts replaced / repaired", "type": "checkbox"},
                    {"key": "work_description", "label": "Detailed Work Description", "type": "textarea", "required": True},
                ],
            },
            {
                "title": "Parts & Materials",
                "fields": [
                    {"key": "parts_used", "label": "Parts / Materials Used", "type": "textarea"},
                    {"key": "part_numbers", "label": "Part Numbers", "type": "text"},
                    {"key": "quantities", "label": "Quantities", "type": "text"},
                ],
            },
            {
                "title": "Post-Maintenance Status",
                "fields": [
                    {"key": "equipment_tested", "label": "Equipment tested after maintenance", "type": "checkbox"},
                    {"key": "test_results", "label": "Test Results (if tested)", "type": "textarea"},
                    {"key": "issues_found", "label": "Issues Found During Maintenance", "type": "textarea"},
                    {"key": "follow_up_required", "label": "Follow-up Action Required", "type": "textarea"},
                    {"key": "next_maintenance_due", "label": "Next Maintenance Due Date", "type": "date"},
                    {"key": "equipment_status", "label": "Equipment Status", "type": "dropdown", "required": True,
                     "options": ["Operational", "Non-Operational", "Requires Further Work", "Under Observation"]},
                ],
            },
        ],
    },

    "generic_equipment_inspection": {
        "key": "generic_equipment_inspection",
        "name": "Generic Equipment Inspection",
        "equipment_type": "Generic",
        "description": "Generic inspection template for equipment inspection activities",
        "supports_multi_session": False,
        "typical_session_interval_days": None,
        "typical_total_sessions": 1,
        "context_bindings": {"manufacturer": "equipment.manufacturer", "serial_number": "equipment.factory_serial_number"},
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Inspection Information",
                "fields": [
                    {"key": "inspection_date", "label": "Inspection Date", "type": "date", "required": True},
                    {"key": "inspection_category", "label": "Inspection Category", "type": "dropdown", "required": True,
                     "options": ["Electrical Safety", "General Maintenance", "Documentation", "Environmental"]},
                    {"key": "inspector_name", "label": "Inspector Name", "type": "text", "required": True},
                    {"key": "inspection_reference", "label": "Inspection Reference / Checklist No.", "type": "text"},
                ],
            },
            {
                "title": "Visual Inspection",
                "fields": [
                    {"key": "physical_condition", "label": "Physical condition satisfactory", "type": "checkbox"},
                    {"key": "no_damage", "label": "No visible damage or corrosion", "type": "checkbox"},
                    {"key": "nameplate_legible", "label": "Nameplate legible and intact", "type": "checkbox"},
                    {"key": "mounting_secure", "label": "Mounting / foundation secure", "type": "checkbox"},
                    {"key": "housekeeping_ok", "label": "Housekeeping / cleanliness acceptable", "type": "checkbox"},
                    {"key": "visual_observations", "label": "Visual Observations / Issues", "type": "textarea"},
                ],
            },
            {
                "title": "Electrical Safety",
                "fields": [
                    {"key": "earthing_intact", "label": "Earthing connections intact", "type": "checkbox"},
                    {"key": "insulation_ok", "label": "Insulation / covers in good condition", "type": "checkbox"},
                    {"key": "clearances_ok", "label": "Electrical clearances maintained", "type": "checkbox"},
                    {"key": "no_overheating", "label": "No signs of overheating", "type": "checkbox"},
                    {"key": "safety_signage", "label": "Safety signage / labels present", "type": "checkbox"},
                    {"key": "electrical_observations", "label": "Electrical Safety Observations", "type": "textarea"},
                ],
            },
            {
                "title": "Documentation",
                "fields": [
                    {"key": "drawings_available", "label": "Equipment drawings available", "type": "checkbox"},
                    {"key": "manuals_available", "label": "Maintenance manuals available", "type": "checkbox"},
                    {"key": "records_updated", "label": "Maintenance records up to date", "type": "checkbox"},
                    {"key": "certificates_valid", "label": "Test certificates valid", "type": "checkbox"},
                    {"key": "doc_observations", "label": "Documentation Observations", "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "deficiencies", "label": "Deficiencies Identified", "type": "textarea"},
                    {"key": "action_required", "label": "Corrective Action Required", "type": "textarea"},
                    {"key": "priority", "label": "Action Priority", "type": "dropdown",
                     "options": ["Low", "Medium", "High", "Critical"]},
                    {"key": "compliance_status", "label": "Compliance Status", "type": "dropdown", "required": True,
                     "options": ["Compliant", "Non-Compliant", "Partial Compliance"]},
                ],
            },
        ],
    },

    # ────────────────────────────────────────────────────────────
    # Dielectric Frequency Response (DFR / IDAX) — Power Transformer
    # Multi-session: FACTORY → SITE_RECEIPT → ON_BED → PRE_COMMISSIONING → MAINTENANCE
    # enable_cross_session=True: each non-FACTORY session is compared vs FACTORY baseline
    # ────────────────────────────────────────────────────────────
    "dfr_idax_transformer": {
        "key": "dfr_idax_transformer",
        "name": "Dielectric Frequency Response (DFR / IDAX)",
        "equipment_type": "Power Transformer",
        "description": "DFR / IDAX insulation diagnostics test for transformer moisture and insulation assessment",
        "supports_multi_session": True,
        "multi_session": True,
        "enable_cross_session": True,
        "typical_session_interval_days": None,
        # total sessions derived from len(session_types) automatically
        "session_types": [
            "FACTORY",
            "SITE_RECEIPT",
            "ON_BED",
            "PRE_COMMISSIONING",
            "MAINTENANCE",
        ],
        "context_bindings": {
            "manufacturer":   "equipment.manufacturer",
            "serial_number":  "equipment.factory_serial_number",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                    {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                ],
            },
            {
                "title": "Transformer Configuration",
                "fields": [
                    {"key": "transformer_type",       "label": "Transformer Type",   "type": "dropdown", "options": ["Two Winding", "Three Winding"], "required": True},
                    {"key": "transformer_rating_mva", "label": "Transformer Rating", "type": "number",   "unit": "MVA", "required": True},
                    {"key": "hv_voltage_kv",          "label": "HV Voltage",         "type": "number",   "unit": "kV",  "required": True},
                    {"key": "lv_voltage_kv",          "label": "LV Voltage",         "type": "number",   "unit": "kV",  "required": True},
                    {"key": "tv_voltage_kv",          "label": "Tertiary Voltage",   "type": "number",   "unit": "kV"},
                ],
            },
            {
                "title": "Test Conditions",
                "fields": [
                    {"key": "test_kit",        "label": "Testing Kit Used",    "type": "text",   "required": True},
                    {"key": "test_voltage_v",  "label": "Test Voltage",        "type": "number", "unit": "V",  "required": True},
                    {"key": "ambient_temp_c",  "label": "Ambient Temperature", "type": "number", "unit": "°C", "required": True},
                    {"key": "oil_temp_c",      "label": "Oil Temperature",     "type": "number", "unit": "°C", "required": True},
                ],
            },
            {
                "title": "DFR Measurement Data",
                "fields": [
                    {
                        "key": "dfr_measurements",
                        "label": "DFR Measurements",
                        "type": "table",
                        "allow_add_rows": True,
                        "allow_delete_rows": True,
                        "columns": [
                            {"key": "frequency_hz",      "label": "Frequency (Hz)",  "type": "number"},
                            {"key": "capacitance_pf",    "label": "Capacitance (pF)","type": "number"},
                            {"key": "tan_delta_percent", "label": "Tan Delta (%)",   "type": "number"},
                        ],
                        # Cross-session: average tan_delta compared vs FACTORY baseline
                        "cross_session_evaluation": {
                            "enabled": True,
                            "baseline": {
                                "strategy": "named_session",
                                "session_name": "FACTORY",
                            },
                            "column_comparisons": {
                                "tan_delta_percent": {
                                    "aggregate_type": "avg",
                                    "deviation_type": "absolute",
                                    "normal_max": 0.3,
                                    "alert_max": None,
                                    "alert_min": None,
                                    "critical_above": 1.5,
                                    "critical_below": None,
                                },
                            },
                        },
                    },
                ],
            },
            {
                "title": "IDAX Analysis Results",
                "fields": [
                    {
                        "key": "analysis_results",
                        "label": "Analysis Results",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "lock_default_rows": False,   # rows pre-filled from default_rows but cells must remain editable
                        "columns": [
                            {"key": "test_configuration",      "label": "Test Configuration",      "type": "readonly"},
                            {"key": "moisture_percent",        "label": "Moisture in Paper (%)",   "type": "number"},
                            {"key": "oil_conductivity_psm",   "label": "Oil Conductivity (pS/m)", "type": "number"},
                            {"key": "moisture_in_oil_percent", "label": "Moisture in Oil (%)",    "type": "number"},
                            {
                                "key": "assessment",
                                "label": "Assessment",
                                "type": "dropdown",
                                "options": ["Very Dry", "Good", "Acceptable", "Wet", "Critical"],
                            },
                        ],
                        "default_rows": [
                            {"test_configuration": "HV-GND"},
                            {"test_configuration": "HV-LV"},
                            {"test_configuration": "LV-GND"},
                            {"test_configuration": "LV-TV"},
                            {"test_configuration": "TV-GND"},
                            {"test_configuration": "TV-HV"},
                        ],
                        # Cross-session: row-by-row vs FACTORY, matched by test_configuration
                        "cross_session_evaluation": {
                            "enabled": True,
                            "baseline": {
                                "strategy": "named_session",
                                "session_name": "FACTORY",
                            },
                            "match_by_column": "test_configuration",
                            "column_comparisons": {
                                "moisture_percent": {
                                    "aggregate_type": None,
                                    "deviation_type": "absolute",
                                    "normal_max": 0.3,
                                    "alert_max": None,
                                    "alert_min": None,
                                    "critical_above": 1.0,
                                    "critical_below": None,
                                },
                                "oil_conductivity_psm": {
                                    "aggregate_type": None,
                                    "deviation_type": "relative_percent",
                                    "normal_max": 20.0,
                                    "alert_max": None,
                                    "alert_min": None,
                                    "critical_above": 50.0,
                                    "critical_below": None,
                                },
                                "moisture_in_oil_percent": {
                                    "aggregate_type": None,
                                    "deviation_type": "absolute",
                                    "normal_max": 5.0,
                                    "alert_max": None,
                                    "alert_min": None,
                                    "critical_above": 15.0,
                                    "critical_below": None,
                                },
                            },
                        },
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result",
                        "label": "Overall Result",
                        "type": "dropdown",
                        "options": ["PASS", "ALERT", "FAIL"],
                        "dropdown_evaluation": {
                            "enabled": True,
                            "value_severities": {
                                "PASS":  "NORMAL",
                                "ALERT": "ALERT",
                                "FAIL":  "CRITICAL",
                            },
                        },
                    },
                    {"key": "observation",    "label": "Observation",   "type": "textarea"},
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

    # ────────────────────────────────────────────────────────────
    # Sweep Frequency Response Analysis (SFRA) — Power Transformer
    # Multi-session: FACTORY → SITE_RECEIPT → ON_BED → PRE_COMMISSIONING → MAINTENANCE
    # enable_cross_session=True: each non-FACTORY session is compared vs FACTORY baseline.
    # SFRA detects mechanical faults: winding deformation/displacement, core movement,
    # shorted turns, and loose connections — by comparing the frequency-response
    # "fingerprint" of each winding against the factory baseline trace.
    # ────────────────────────────────────────────────────────────
    "sfra_transformer": {
        "key": "sfra_transformer",
        "name": "Sweep Frequency Response Analysis (SFRA)",
        "equipment_type": "Power Transformer",
        "description": "SFRA mechanical-integrity diagnostics — compares each winding's frequency-response fingerprint against the factory baseline to detect winding/core deformation (per IEC 60076-18 / CIGRE 342)",
        "supports_multi_session": True,
        "multi_session": True,
        "enable_cross_session": True,
        "typical_session_interval_days": None,
        # total sessions derived from len(session_types) automatically
        "session_types": [
            "FACTORY",
            "SITE_RECEIPT",
            "ON_BED",
            "PRE_COMMISSIONING",
            "MAINTENANCE",
        ],
        "context_bindings": {
            "manufacturer":  "equipment.manufacturer",
            "serial_number": "equipment.factory_serial_number",
            "vector_group":  "equipment.vector_group",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "manufacturer", "label": "Manufacturer", "type": "readonly"},
                    {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                    {"key": "vector_group", "label": "Vector Group", "type": "readonly"},
                ],
            },
            {
                "title": "Transformer Configuration",
                "fields": [
                    {"key": "transformer_type",       "label": "Transformer Type",   "type": "dropdown", "options": ["Two Winding", "Three Winding"], "required": True},
                    {"key": "transformer_rating_mva", "label": "Transformer Rating", "type": "number",   "unit": "MVA", "required": True},
                    {"key": "hv_voltage_kv",          "label": "HV Voltage",         "type": "number",   "unit": "kV",  "required": True},
                    {"key": "lv_voltage_kv",          "label": "LV Voltage",         "type": "number",   "unit": "kV",  "required": True},
                    {"key": "tv_voltage_kv",          "label": "Tertiary Voltage",   "type": "number",   "unit": "kV"},
                ],
            },
            {
                "title": "Test Conditions",
                "fields": [
                    {"key": "test_kit",          "label": "Testing Kit Used",       "type": "text",   "required": True},
                    {"key": "sweep_range",       "label": "Sweep Frequency Range",  "type": "text",   "required": True},  # e.g. "20 Hz – 2 MHz"
                    {"key": "measurement_points","label": "No. of Measurement Points","type": "number"},
                    {"key": "tap_position",      "label": "Tap Position",           "type": "text"},
                    {"key": "ambient_temp_c",    "label": "Ambient Temperature",    "type": "number", "unit": "°C", "required": True},
                    {"key": "oil_temp_c",        "label": "Oil Temperature",        "type": "number", "unit": "°C", "required": True},
                ],
            },
            {
                "title": "SFRA Trace Data",
                "fields": [
                    {
                        "key": "sfra_measurements",
                        "label": "SFRA Measurements (Amplitude vs Frequency)",
                        "type": "table",
                        "allow_add_rows": True,
                        "allow_delete_rows": True,
                        "columns": [
                            {"key": "winding",           "label": "Winding / Connection", "type": "text"},   # e.g. HV-N, LV-N, HV-LV
                            {"key": "frequency_hz",      "label": "Frequency (Hz)",       "type": "number"},
                            {"key": "amplitude_db",      "label": "Amplitude (dB)",       "type": "number"},
                            {"key": "phase_deg",         "label": "Phase (°)",            "type": "number"},
                        ],
                        # Cross-session: amplitude trace compared row-by-row vs FACTORY,
                        # matched by frequency. Absolute dB deviation flags movement.
                        "cross_session_evaluation": {
                            "enabled": True,
                            "baseline": {
                                "strategy": "named_session",
                                "session_name": "FACTORY",
                            },
                            "match_by_column": "frequency_hz",
                            "column_comparisons": {
                                # Amplitude deviation is bidirectional — a winding/core
                                # shift can move the trace UP or DOWN. Thresholds are
                                # symmetric so |deviation| drives the status:
                                #   |dev| <= 3 dB → NORMAL, 3–6 dB → ALERT, > 6 dB → CRITICAL
                                "amplitude_db": {
                                    "aggregate_type": None,
                                    "deviation_type": "absolute",
                                    "normal_min": -3.0,
                                    "normal_max": 3.0,
                                    "alert_min": None,
                                    "alert_max": None,
                                    "critical_below": -6.0,
                                    "critical_above": 6.0,
                                },
                            },
                        },
                    },
                ],
            },
            {
                "title": "Correlation Coefficient Analysis",
                "fields": [
                    {
                        "key": "correlation_analysis",
                        "label": "Per-Winding Correlation vs Factory Baseline",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "lock_default_rows": False,   # rows pre-filled; cells remain editable
                        "columns": [
                            {"key": "winding",   "label": "Winding",                       "type": "readonly"},
                            {"key": "cc_lf",     "label": "CC — LF (1k–100kHz)",           "type": "number"},
                            {"key": "cc_mf",     "label": "CC — MF (100k–600kHz)",         "type": "number"},
                            {"key": "cc_hf",     "label": "CC — HF (600k–1MHz)",           "type": "number"},
                            {
                                "key": "assessment",
                                "label": "Assessment",
                                "type": "dropdown",
                                "options": ["Normal", "Slight Deviation", "Marginal", "Abnormal"],
                            },
                        ],
                        "default_rows": [
                            {"winding": "HV-N"},
                            {"winding": "LV-N"},
                            {"winding": "TV-N"},
                            {"winding": "HV-LV"},
                            {"winding": "HV-TV"},
                            {"winding": "LV-TV"},
                        ],
                        # Correlation coefficient (0–1, higher = closer to baseline).
                        # Static per-column acceptance floors — a CC below the floor
                        # signals a mechanical change in that frequency band, independent
                        # of any baseline session (baseline CC is ~1.0 against itself).
                        "table_evaluation": {
                            "enabled": True,
                            "remedial_action_text": "SFRA correlation below acceptance floor — investigate winding/core mechanical integrity before energising",
                            "column_evaluations": {
                                # LF band — core, magnetizing branch, winding clamping
                                "cc_lf": {"normal_min": 0.98, "alert_min": 0.95, "critical_below": 0.95},
                                # MF band — bulk winding movement / axial displacement
                                "cc_mf": {"normal_min": 0.98, "alert_min": 0.95, "critical_below": 0.95},
                                # HF band — winding/lead deformation, loose connections
                                "cc_hf": {"normal_min": 0.97, "alert_min": 0.93, "critical_below": 0.93},
                            },
                        },
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result",
                        "label": "Overall Result",
                        "type": "dropdown",
                        "options": ["PASS", "ALERT", "FAIL"],
                        "dropdown_evaluation": {
                            "enabled": True,
                            "value_severities": {
                                "PASS":  "NORMAL",
                                "ALERT": "ALERT",
                                "FAIL":  "CRITICAL",
                            },
                        },
                    },
                    {
                        "key": "fault_type",
                        "label": "Suspected Fault Type",
                        "type": "dropdown",
                        "options": [
                            "None",
                            "Winding Deformation",
                            "Axial Displacement",
                            "Radial Displacement / Buckling",
                            "Shorted Turns",
                            "Core Movement",
                            "Loose Connection / Lead",
                        ],
                    },
                    {"key": "observation",    "label": "Observation",    "type": "textarea"},
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

    # ────────────────────────────────────────────────────────────
    # Tan-Delta, Capacitance & Insulation Diagnostics (KPTCL R&D)
    # Single-session combined test: DELTA 4000 + IDAX 300
    # Covers winding tests + bushing tests + IDAX moisture/conductivity
    # ────────────────────────────────────────────────────────────
    "tan_delta_capacitance_idax": {
        "key": "tan_delta_capacitance_idax",
        "name": "Tan-Delta, Capacitance & Insulation Diagnostics",
        "equipment_type": "Power Transformer",
        "description": "Combined Tan-Delta/Capacitance (DELTA 4000) and Insulation Diagnostics (IDAX) test report for Power Transformers — winding and bushing measurements with historical comparison.",
        "supports_multi_session": False,
        "typical_total_sessions": 1,
        "context_bindings": {
            "make":               "equipment.manufacturer",
            "capacity_mva":       "nameplate.rated_mva",
            "serial_number":      "equipment.factory_serial_number",
            "year_of_manufacture":"nameplate.yom",
            "vector_group":       "equipment.vector_group",
            "doc":                "nameplate.date_of_commission",
        },
        "sections": [
            {
                "title": "Equipment Details",
                "collapsed": True,
                "fields": [
                    {"key": "make", "label": "Manufacturer", "type": "readonly"},
                    {"key": "serial_number", "label": "Serial Number", "type": "readonly"},
                    {"key": "capacity_mva", "label": "Rated MVA", "type": "readonly"},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "readonly"},
                    {"key": "vector_group", "label": "Vector Group", "type": "readonly"},
                    {"key": "doc", "label": "Date of Commission", "type": "readonly"},
                ],
            },
            # ── Test Information ──────────────────────────────────────────────
            {
                "title": "Test Information",
                "fields": [
                    {"key": "date_of_previous_test", "label": "Date of Previous Test", "type": "date"},
                    {"key": "weather_condition",     "label": "Weather Condition",      "type": "text", "placeholder": "e.g. Sunny, Cloudy"},
                    {"key": "ambient_temp_c",        "label": "Ambient Temperature",    "type": "number", "unit": "°C", "required": True},
                ],
            },
            # ── Transformer Details ───────────────────────────────────────────
            {
                "title": "Transformer Details",
                "fields": [
                    {"key": "voltage_ratio", "label": "Voltage Ratio", "type": "text", "placeholder": "e.g. 220/66/11 kV"},
                    {"key": "oil_temp_c",    "label": "Oil Temperature","type": "number", "unit": "°C"},
                ],
            },
            # ── Tan-Delta & Capacitance Test ──────────────────────────────────
            {
                "title": "Tan-Delta & Capacitance Test",
                "fields": [
                    {
                        "key": "tan_delta_kit",
                        "label": "Testing Kit Used",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. Tan-delta kit of Megger make, Model: DELTA 4000",
                    },
                    # a. Winding Test Results
                    {
                        "key": "winding_test_results",
                        "label": "a. Winding Test Results",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "lock_default_rows": False,
                        "columns": [
                            {"key": "test_configuration",  "label": "Test Configuration",              "type": "readonly"},
                            {"key": "kv",                  "label": "kV",                              "type": "number"},
                            {"key": "capacitance_pf",      "label": "Capacitance C (pF)",              "type": "number"},
                            {"key": "df_measured",         "label": "% D.F Measured",                  "type": "number"},
                            {"key": "itc_correction_factor","label": "ITC Correction Factor",          "type": "number"},
                            {"key": "df_corrected_20c",    "label": "% D.F @ 20°C (ITC Corrected)",   "type": "calculated", "formula": "multiply(df_measured, itc_correction_factor)"},
                            {"key": "df_previous_test",    "label": "% D.F Previous Test",             "type": "number"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "df_corrected_20c",
                                        "thresholds": {
                                            "Winding % D.F @ 20°C (IEEE/IEC)": {
                                                "Good": [None, 0.5],
                                                "Fair": [0.5,  1.0],
                                                "Poor": [1.0,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                        "default_rows": [
                            {"test_configuration": "HV-GND"},
                            {"test_configuration": "HV-LV"},
                            {"test_configuration": "LV-GND"},
                            {"test_configuration": "LV-TV"},
                            {"test_configuration": "TV-GND"},
                            {"test_configuration": "HV-TV"},
                        ],
                    },
                    # Bushing identity (Make/Sl.No./Y.O.Mfg) comes from the
                    # Equipment register nameplate (bushing_details) — not re-entered here.
                    # a. 220kV Bushing Test Results
                    {
                        "key": "bushing_220kv_results",
                        "label": "220kV Bushing Test Results",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "lock_default_rows": False,
                        "columns": [
                            {"key": "bushing",              "label": "Bushing",                          "type": "readonly"},
                            {"key": "kv",                   "label": "kV",                               "type": "number"},
                            {"key": "capacitance_pf",       "label": "Capacitance C (pF)",               "type": "number"},
                            {"key": "df_measured",          "label": "% D.F Measured",                   "type": "number"},
                            {"key": "itc_correction_factor","label": "ITC Correction Factor",            "type": "number"},
                            {"key": "df_corrected_20c",     "label": "% D.F @ 20°C (ITC Corrected)",    "type": "calculated", "formula": "multiply(df_measured, itc_correction_factor)"},
                            {"key": "df_previous_test",     "label": "% D.F Previous Test",              "type": "number"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "df_corrected_20c",
                                        "thresholds": {
                                            "220kV Bushing % D.F @ 20°C (IEC OIP)": {
                                                "Good":  [None, 0.5],
                                                "Alert": [0.5,  0.7],
                                                "Poor":  [0.7,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                        "default_rows": [
                            {"bushing": "'R' Phase"},
                            {"bushing": "'Y' Phase"},
                            {"bushing": "'B' Phase"},
                        ],
                    },
                    # b. 66kV Bushing Test Results (identity from nameplate register)
                    {
                        "key": "bushing_66kv_results",
                        "label": "66kV Bushing Test Results",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "lock_default_rows": False,
                        "columns": [
                            {"key": "bushing",              "label": "Bushing",                          "type": "readonly"},
                            {"key": "kv",                   "label": "kV",                               "type": "number"},
                            {"key": "capacitance_pf",       "label": "Capacitance C (pF)",               "type": "number"},
                            {"key": "df_measured",          "label": "% D.F Measured",                   "type": "number"},
                            {"key": "itc_correction_factor","label": "ITC Correction Factor",            "type": "number"},
                            {"key": "df_corrected_20c",     "label": "% D.F @ 20°C (ITC Corrected)",    "type": "calculated", "formula": "multiply(df_measured, itc_correction_factor)"},
                            {"key": "df_previous_test",     "label": "% D.F Previous Test",              "type": "number"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "df_corrected_20c",
                                        "thresholds": {
                                            "66kV Bushing % D.F @ 20°C (IEC OIP)": {
                                                "Good":  [None, 0.7],
                                                "Alert": [0.7,  1.0],
                                                "Poor":  [1.0,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                        "default_rows": [
                            {"bushing": "'R' Phase"},
                            {"bushing": "'Y' Phase"},
                            {"bushing": "'B' Phase"},
                        ],
                    },
                    {"key": "tan_delta_observations", "label": "Observations", "type": "textarea"},
                ],
            },
            # ── Insulation Diagnostics Test (IDAX) ───────────────────────────
            {
                "title": "Insulation Diagnostics Test (IDAX)",
                "fields": [
                    {
                        "key": "idax_kit",
                        "label": "Testing Kit Used",
                        "type": "text",
                        "required": True,
                        "placeholder": "e.g. IDAX kit of Megger make, Model: IDAX 300",
                    },
                    {
                        "key": "insulation_diagnostics",
                        "label": "Insulation Diagnostics Results",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "lock_default_rows": False,
                        "columns": [
                            {"key": "test_configuration",         "label": "Test Configuration",                    "type": "readonly"},
                            {"key": "moisture_percent",            "label": "% Moisture",                            "type": "number"},
                            {"key": "moisture_analysis",          "label": "Tr. Analysis (% Moisture)",             "type": "dropdown",
                             "options": ["As new", "Dry", "Moderately Wet", "Wet", "Very Wet"]},
                            {"key": "moisture_previous_test",     "label": "% Moisture Previous Test",              "type": "number"},
                            {"key": "oil_conductivity_psm",       "label": "Oil Conductivity (pS/m)",               "type": "number"},
                            {"key": "oil_conductivity_analysis",  "label": "Tr. Analysis (Oil Conductivity)",       "type": "dropdown",
                             "options": ["As new", "Acceptable", "Poor", "Bad"]},
                        ],
                        "default_rows": [
                            {"test_configuration": "HV-GND"},
                            {"test_configuration": "HV-LV"},
                            {"test_configuration": "LV-GND"},
                            {"test_configuration": "LV-TV"},
                            {"test_configuration": "TV-GND"},
                            {"test_configuration": "HV-TV"},
                        ],
                    },
                    {"key": "idax_observations", "label": "Observations", "type": "textarea"},
                ],
            },
            # ── Overall Assessment ────────────────────────────────────────────
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result",
                        "label": "Overall Result",
                        "type": "dropdown",
                        "options": ["PASS", "CONDITIONAL", "FAIL"],
                        "required": True,
                        "dropdown_evaluation": {
                            "enabled": True,
                            "value_severities": {
                                "PASS":        "NORMAL",
                                "CONDITIONAL": "ALERT",
                                "FAIL":        "CRITICAL",
                            },
                        },
                    },
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

    # ────────────────────────────────────────────────────────────
    # INDIVIDUAL TESTS — single-session, executable on their own.
    # Consolidated report combines whichever ran per transformer.
    # ────────────────────────────────────────────────────────────

    # ── Winding Tan-Delta & Capacitance (individual) ──────────────
    "tan_delta_winding": {
        "key": "tan_delta_winding",
        "name": "Winding Tan-Delta & Capacitance Test",
        "equipment_type": "Power Transformer",
        "description": "Winding insulation Tan-Delta and capacitance measurement (DELTA 4000) with historical comparison.",
        "supports_multi_session": False,
        "typical_total_sessions": 1,
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "tan_delta_kit",         "label": "Testing Kit Used",    "type": "text", "required": True, "placeholder": "e.g. Megger DELTA 4000"},
                    {"key": "date_of_previous_test", "label": "Date of Previous Test","type": "date"},
                    {"key": "weather_condition",     "label": "Weather Condition",   "type": "text"},
                    {"key": "ambient_temp_c",        "label": "Ambient Temperature", "type": "number", "unit": "°C", "required": True},
                    {"key": "oil_temp_c",            "label": "Oil Temperature",     "type": "number", "unit": "°C"},
                ],
            },
            {
                "title": "Winding Test Results",
                "fields": [
                    {
                        "key": "winding_test_results",
                        "label": "Winding Test Results",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "lock_default_rows": False,
                        "columns": [
                            {"key": "test_configuration",   "label": "Test Configuration",            "type": "readonly"},
                            {"key": "kv",                   "label": "kV",                            "type": "number"},
                            {"key": "capacitance_pf",       "label": "Capacitance C (pF)",            "type": "number"},
                            {"key": "df_measured",          "label": "% D.F Measured",                "type": "number"},
                            {"key": "itc_correction_factor","label": "ITC Correction Factor",         "type": "number"},
                            {"key": "df_corrected_20c",     "label": "% D.F @ 20°C (Corrected)",     "type": "calculated", "formula": "multiply(df_measured, itc_correction_factor)"},
                            {"key": "df_previous_test",     "label": "% D.F Previous Test",           "type": "number"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "df_corrected_20c",
                                        "thresholds": {
                                            "Winding % D.F @ 20°C (IEEE/IEC)": {
                                                "Good": [None, 0.5],
                                                "Fair": [0.5,  1.0],
                                                "Poor": [1.0,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                        "default_rows": [
                            {"test_configuration": "HV-GND"},
                            {"test_configuration": "HV-LV"},
                            {"test_configuration": "LV-GND"},
                            {"test_configuration": "LV-TV"},
                            {"test_configuration": "TV-GND"},
                            {"test_configuration": "HV-TV"},
                        ],
                        "table_evaluation": {
                            "enabled": True,
                            "column_evaluations": {
                                # IEEE/IEC winding power-factor guidance (corrected to 20°C)
                                "df_corrected_20c": {
                                    "normal_min": None,    "normal_max": 0.5,
                                    "alert_min": None,     "alert_max": None,
                                    "critical_below": None, "critical_above": 1.0,
                                },
                            },
                        },
                    },
                    {"key": "observations", "label": "Observations", "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result", "label": "Overall Result", "type": "dropdown",
                        "options": ["PASS", "CONDITIONAL", "FAIL"], "required": True,
                        "dropdown_evaluation": {"enabled": True, "value_severities": {"PASS": "NORMAL", "CONDITIONAL": "ALERT", "FAIL": "CRITICAL"}},
                    },
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

    # ── 220kV Bushing Tan-Delta (individual) ──────────────────────
    "tan_delta_bushing_220kv": {
        "key": "tan_delta_bushing_220kv",
        "name": "220kV Bushing Tan-Delta Test",
        "equipment_type": "Power Transformer",
        "description": "220kV bushing Tan-Delta and capacitance measurement (R/Y/B phases) with historical comparison.",
        "supports_multi_session": False,
        "typical_total_sessions": 1,
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "tan_delta_kit",         "label": "Testing Kit Used",    "type": "text", "required": True},
                    {"key": "date_of_previous_test", "label": "Date of Previous Test","type": "date"},
                    {"key": "ambient_temp_c",        "label": "Ambient Temperature", "type": "number", "unit": "°C", "required": True},
                ],
            },
            {
                "title": "220kV Bushing Test Results",
                "fields": [
                    {
                        "key": "bushing_test_results", "label": "220kV Bushing Test Results", "type": "table",
                        "allow_add_rows": False, "allow_delete_rows": False, "lock_default_rows": False,
                        "columns": [
                            {"key": "bushing",              "label": "Bushing",                       "type": "readonly"},
                            {"key": "kv",                   "label": "kV",                            "type": "number"},
                            {"key": "capacitance_pf",       "label": "Capacitance C (pF)",            "type": "number"},
                            {"key": "df_measured",          "label": "% D.F Measured",                "type": "number"},
                            {"key": "itc_correction_factor","label": "ITC Correction Factor",         "type": "number"},
                            {"key": "df_corrected_20c",     "label": "% D.F @ 20°C (Corrected)",     "type": "calculated", "formula": "multiply(df_measured, itc_correction_factor)"},
                            {"key": "df_previous_test",     "label": "% D.F Previous Test",           "type": "number"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "df_corrected_20c",
                                        "thresholds": {
                                            "220kV Bushing % D.F @ 20°C (IEC OIP)": {
                                                "Good":  [None, 0.5],
                                                "Alert": [0.5,  0.7],
                                                "Poor":  [0.7,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                        "default_rows": [{"bushing": "'R' Phase"}, {"bushing": "'Y' Phase"}, {"bushing": "'B' Phase"}],
                        "table_evaluation": {
                            "enabled": True,
                            "column_evaluations": {
                                # 220kV OIP bushing power-factor limits
                                "df_corrected_20c": {
                                    "normal_min": None,    "normal_max": 0.5,
                                    "alert_min": None,     "alert_max": None,
                                    "critical_below": None, "critical_above": 0.7,
                                },
                            },
                        },
                    },
                    {"key": "observations", "label": "Observations", "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result", "label": "Overall Result", "type": "dropdown",
                        "options": ["PASS", "CONDITIONAL", "FAIL"], "required": True,
                        "dropdown_evaluation": {"enabled": True, "value_severities": {"PASS": "NORMAL", "CONDITIONAL": "ALERT", "FAIL": "CRITICAL"}},
                    },
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

    # ── 66kV Bushing Tan-Delta (individual) ───────────────────────
    "tan_delta_bushing_66kv": {
        "key": "tan_delta_bushing_66kv",
        "name": "66kV Bushing Tan-Delta Test",
        "equipment_type": "Power Transformer",
        "description": "66kV bushing Tan-Delta and capacitance measurement (R/Y/B phases) with historical comparison.",
        "supports_multi_session": False,
        "typical_total_sessions": 1,
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "tan_delta_kit",         "label": "Testing Kit Used",    "type": "text", "required": True},
                    {"key": "date_of_previous_test", "label": "Date of Previous Test","type": "date"},
                    {"key": "ambient_temp_c",        "label": "Ambient Temperature", "type": "number", "unit": "°C", "required": True},
                ],
            },
            {
                "title": "66kV Bushing Test Results",
                "fields": [
                    {
                        "key": "bushing_test_results", "label": "66kV Bushing Test Results", "type": "table",
                        "allow_add_rows": False, "allow_delete_rows": False, "lock_default_rows": False,
                        "columns": [
                            {"key": "bushing",              "label": "Bushing",                       "type": "readonly"},
                            {"key": "kv",                   "label": "kV",                            "type": "number"},
                            {"key": "capacitance_pf",       "label": "Capacitance C (pF)",            "type": "number"},
                            {"key": "df_measured",          "label": "% D.F Measured",                "type": "number"},
                            {"key": "itc_correction_factor","label": "ITC Correction Factor",         "type": "number"},
                            {"key": "df_corrected_20c",     "label": "% D.F @ 20°C (Corrected)",     "type": "calculated", "formula": "multiply(df_measured, itc_correction_factor)"},
                            {"key": "df_previous_test",     "label": "% D.F Previous Test",           "type": "number"},
                            {
                                "key": "condition",
                                "label": "Condition",
                                "type": "calculated",
                                "read_only": True,
                                "rule": {
                                    "type": "THRESHOLD",
                                    "config": {
                                        "input_field": "df_corrected_20c",
                                        "thresholds": {
                                            "66kV Bushing % D.F @ 20°C (IEC OIP)": {
                                                "Good":  [None, 0.7],
                                                "Alert": [0.7,  1.0],
                                                "Poor":  [1.0,  None],
                                            }
                                        }
                                    }
                                }
                            },
                        ],
                        "default_rows": [{"bushing": "'R' Phase"}, {"bushing": "'Y' Phase"}, {"bushing": "'B' Phase"}],
                        "table_evaluation": {
                            "enabled": True,
                            "column_evaluations": {
                                # 66kV OIP bushing power-factor limits
                                "df_corrected_20c": {
                                    "normal_min": None,    "normal_max": 0.7,
                                    "alert_min": None,     "alert_max": None,
                                    "critical_below": None, "critical_above": 1.0,
                                },
                            },
                        },
                    },
                    {"key": "observations", "label": "Observations", "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result", "label": "Overall Result", "type": "dropdown",
                        "options": ["PASS", "CONDITIONAL", "FAIL"], "required": True,
                        "dropdown_evaluation": {"enabled": True, "value_severities": {"PASS": "NORMAL", "CONDITIONAL": "ALERT", "FAIL": "CRITICAL"}},
                    },
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

    # ── IDAX Insulation Diagnostics (individual) ──────────────────
    "idax_insulation": {
        "key": "idax_insulation",
        "name": "Insulation Diagnostics (IDAX)",
        "equipment_type": "Power Transformer",
        "description": "IDAX insulation diagnostics — % moisture and oil conductivity per winding configuration with historical comparison.",
        "supports_multi_session": False,
        "typical_total_sessions": 1,
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "idax_kit",              "label": "Testing Kit Used",    "type": "text", "required": True, "placeholder": "e.g. Megger IDAX 300"},
                    {"key": "date_of_previous_test", "label": "Date of Previous Test","type": "date"},
                    {"key": "ambient_temp_c",        "label": "Ambient Temperature", "type": "number", "unit": "°C", "required": True},
                    {"key": "oil_temp_c",            "label": "Oil Temperature",     "type": "number", "unit": "°C"},
                ],
            },
            {
                "title": "Insulation Diagnostics Results",
                "fields": [
                    {
                        "key": "insulation_diagnostics", "label": "Insulation Diagnostics Results", "type": "table",
                        "allow_add_rows": False, "allow_delete_rows": False, "lock_default_rows": False,
                        "columns": [
                            {"key": "test_configuration",        "label": "Test Configuration",              "type": "readonly"},
                            {"key": "moisture_percent",          "label": "% Moisture",                      "type": "number"},
                            {"key": "moisture_analysis",         "label": "Tr. Analysis (% Moisture)",       "type": "dropdown", "options": ["As new", "Dry", "Moderately Wet", "Wet", "Very Wet"], "column_evaluation": _EV_MOISTURE},
                            {"key": "moisture_previous_test",    "label": "% Moisture Previous Test",        "type": "number"},
                            {"key": "oil_conductivity_psm",      "label": "Oil Conductivity (pS/m)",         "type": "number"},
                            {"key": "oil_conductivity_analysis", "label": "Tr. Analysis (Oil Conductivity)", "type": "dropdown", "options": ["As new", "Acceptable", "Poor", "Bad"], "column_evaluation": _EV_OIL_COND},
                        ],
                        "default_rows": [
                            {"test_configuration": "HV-GND"},
                            {"test_configuration": "HV-LV"},
                            {"test_configuration": "LV-GND"},
                            {"test_configuration": "LV-TV"},
                            {"test_configuration": "TV-GND"},
                            {"test_configuration": "HV-TV"},
                        ],
                        "table_evaluation": {
                            "enabled": True,
                            "column_evaluations": {
                                "moisture_percent": {
                                    "normal_min": None,    "normal_max": 2.0,
                                    "alert_min": None,     "alert_max": None,
                                    "critical_below": None, "critical_above": 3.0,
                                },
                            },
                        },
                    },
                    {"key": "observations", "label": "Observations", "type": "textarea"},
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result", "label": "Overall Result", "type": "dropdown",
                        "options": ["PASS", "CONDITIONAL", "FAIL"], "required": True,
                        "dropdown_evaluation": {"enabled": True, "value_severities": {"PASS": "NORMAL", "CONDITIONAL": "ALERT", "FAIL": "CRITICAL"}},
                    },
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

    # ── DFR (single-session, routine/maintenance — no baseline) ───────────────
    "dfr_routine": {
        "key": "dfr_routine",
        "name": "Dielectric Frequency Response (DFR) — Routine",
        "equipment_type": "Power Transformer",
        "description": "Single-session Dielectric Frequency Response measurement for routine/maintenance testing (no factory-baseline comparison).",
        "supports_multi_session": False,
        "typical_total_sessions": 1,
        "sections": [
            {
                "title": "Test Conditions",
                "fields": [
                    {"key": "test_kit",         "label": "Testing Kit Used",    "type": "text",   "required": True},
                    {"key": "test_voltage_v",   "label": "Test Voltage",        "type": "number", "unit": "V",  "required": True},
                    {"key": "ambient_temp_c",   "label": "Ambient Temperature", "type": "number", "unit": "°C", "required": True},
                    {"key": "oil_temp_c",       "label": "Oil Temperature",     "type": "number", "unit": "°C", "required": True},
                ],
            },
            {
                "title": "DFR Measurement Data",
                "fields": [
                    {
                        "key": "dfr_measurements",
                        "label": "DFR Measurements",
                        "type": "table",
                        "allow_add_rows": True,
                        "allow_delete_rows": True,
                        "columns": [
                            {"key": "frequency_hz",      "label": "Frequency (Hz)",   "type": "number"},
                            {"key": "capacitance_pf",    "label": "Capacitance (pF)", "type": "number"},
                            {"key": "tan_delta_percent", "label": "Tan Delta (%)",    "type": "number"},
                        ],
                        "table_evaluation": {
                            "enabled": True,
                            "column_evaluations": {
                                "tan_delta_percent": {
                                    "normal_min": None,    "normal_max": 0.5,
                                    "alert_min": None,     "alert_max": None,
                                    "critical_below": None, "critical_above": 1.0,
                                },
                            },
                        },
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result", "label": "Overall Result", "type": "dropdown",
                        "options": ["PASS", "ALERT", "FAIL"], "required": True,
                        "dropdown_evaluation": {"enabled": True, "value_severities": {"PASS": "NORMAL", "ALERT": "ALERT", "FAIL": "CRITICAL"}},
                    },
                    {"key": "observation",    "label": "Observation",    "type": "textarea"},
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

    # ── SFRA (single-session, routine/maintenance — static CC floors) ─────────
    "sfra_routine": {
        "key": "sfra_routine",
        "name": "Sweep Frequency Response Analysis (SFRA) — Routine",
        "equipment_type": "Power Transformer",
        "description": "Single-session SFRA measurement for routine/maintenance testing. Uses static correlation-coefficient acceptance floors (no factory-baseline session).",
        "supports_multi_session": False,
        "typical_total_sessions": 1,
        "sections": [
            {
                "title": "Test Conditions",
                "fields": [
                    {"key": "test_kit",          "label": "Testing Kit Used",         "type": "text",   "required": True},
                    {"key": "sweep_range",       "label": "Sweep Frequency Range",    "type": "text",   "required": True},
                    {"key": "measurement_points","label": "No. of Measurement Points","type": "number"},
                    {"key": "tap_position",      "label": "Tap Position",             "type": "text"},
                    {"key": "ambient_temp_c",    "label": "Ambient Temperature",      "type": "number", "unit": "°C", "required": True},
                    {"key": "oil_temp_c",        "label": "Oil Temperature",          "type": "number", "unit": "°C", "required": True},
                ],
            },
            {
                "title": "SFRA Trace Data",
                "fields": [
                    {
                        "key": "sfra_measurements",
                        "label": "SFRA Measurements (Amplitude vs Frequency)",
                        "type": "table",
                        "allow_add_rows": True,
                        "allow_delete_rows": True,
                        "columns": [
                            {"key": "winding",      "label": "Winding / Connection", "type": "text"},
                            {"key": "frequency_hz", "label": "Frequency (Hz)",       "type": "number"},
                            {"key": "amplitude_db", "label": "Amplitude (dB)",       "type": "number"},
                            {"key": "phase_deg",    "label": "Phase (°)",            "type": "number"},
                        ],
                    },
                ],
            },
            {
                "title": "Correlation Coefficient Analysis",
                "fields": [
                    {
                        "key": "correlation_analysis",
                        "label": "Per-Winding Correlation",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "lock_default_rows": False,
                        "columns": [
                            {"key": "winding",   "label": "Winding",               "type": "readonly"},
                            {"key": "cc_lf",     "label": "CC — LF (1k–100kHz)",   "type": "number"},
                            {"key": "cc_mf",     "label": "CC — MF (100k–600kHz)", "type": "number"},
                            {"key": "cc_hf",     "label": "CC — HF (600k–1MHz)",   "type": "number"},
                            {"key": "assessment","label": "Assessment", "type": "dropdown",
                             "options": ["Normal", "Slight Deviation", "Marginal", "Abnormal"],
                             "column_evaluation": _EV_SFRA_ASSESS},
                        ],
                        "default_rows": [
                            {"winding": "HV-N"}, {"winding": "LV-N"}, {"winding": "TV-N"},
                            {"winding": "HV-LV"}, {"winding": "HV-TV"}, {"winding": "LV-TV"},
                        ],
                        "table_evaluation": {
                            "enabled": True,
                            "remedial_action_text": "SFRA correlation below acceptance floor — investigate winding/core mechanical integrity",
                            "column_evaluations": {
                                "cc_lf": {"normal_min": 0.98, "normal_max": None, "alert_min": 0.95, "alert_max": None, "critical_below": 0.95, "critical_above": None},
                                "cc_mf": {"normal_min": 0.98, "normal_max": None, "alert_min": 0.95, "alert_max": None, "critical_below": 0.95, "critical_above": None},
                                "cc_hf": {"normal_min": 0.97, "normal_max": None, "alert_min": 0.93, "alert_max": None, "critical_below": 0.93, "critical_above": None},
                            },
                        },
                    },
                ],
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {
                        "key": "overall_result", "label": "Overall Result", "type": "dropdown",
                        "options": ["PASS", "ALERT", "FAIL"], "required": True,
                        "dropdown_evaluation": {"enabled": True, "value_severities": {"PASS": "NORMAL", "ALERT": "ALERT", "FAIL": "CRITICAL"}},
                    },
                    {
                        "key": "fault_type", "label": "Suspected Fault Type", "type": "dropdown",
                        "options": ["None", "Winding Deformation", "Axial Displacement",
                                    "Radial Displacement / Buckling", "Shorted Turns",
                                    "Core Movement", "Loose Connection / Lead"],
                    },
                    {"key": "observation",    "label": "Observation",    "type": "textarea"},
                    {"key": "recommendation", "label": "Recommendation", "type": "textarea"},
                ],
            },
        ],
    },

}


# ── Request-category → template key mapping ──────────────────────────────────
# Used when a TestingRequest is created with a specific request_category but no
# explicit test_type_id. Flutter resolves the form template via this map.
REQUEST_CATEGORY_TO_TEMPLATE = {
    "maintenance":      "transformer_maintenance",
    "inspection":       "transformer_inspection",
    "repair_lifecycle": "transformer_repair_lifecycle",
    # 'test' category uses test_type_id / TEST_TYPE_TO_TEMPLATE instead
}


TEST_TYPE_TO_TEMPLATE = {
    # ── Protection Relay ──
    "Protection Relay Functional Test":    "protection_relay_functional_test",
    # ── Current Transformer ──
    "Insulation Resistance (IR) Test":     "insulation_resistance_test",
    "CT Ratio Test":                       "ct_ratio_test",
    "Core Insulation Test":                "core_insulation_test",
    # ── New mappings from HTML mockups ──
    # Meter
    "Meter Testing": "meter_testing",
    # Relay
    "Relay Testing": "relay_testing",
    # Power Transformer
    "Power Transformer Nameplate Details": "power_transformer_nameplate",
    "Transformer Physical Inspection": "transformer_physical_inspection",
    "Ratio Test HV-IV": "ratio_test_hv_iv",
    "Ratio Test HV-LV": "ratio_test_hv_lv",
    "Short Circuit Test HV-IV": "short_circuit_test_hv_iv",
    "Short Circuit Test HV-LV": "short_circuit_test_hv_lv",
    "Magnetic Balance Test HV": "magnetic_balance_test_hv",
    "Magnetic Balance Test IV": "magnetic_balance_test_iv",
    "Magnetic Balance Test LV": "magnetic_balance_test_lv",
    "Open Circuit Test HV-IV (1Ph)": "open_circuit_test_hv_iv_1ph",
    "Open Circuit Test HV-IV (3Ph)": "open_circuit_test_hv_iv_3ph",
    "Open Circuit Test HV-LV (1Ph)": "open_circuit_test_hv_lv_1ph",
    "Open Circuit Test HV-LV (3Ph)": "open_circuit_test_hv_lv_3ph",
    "Open Circuit Test IV-LV (1Ph)": "open_circuit_test_iv_lv_1ph",
    "Open Circuit Test IV-LV (3Ph)": "open_circuit_test_iv_lv_3ph",
    "Capacitance & Tan Delta Test (Transformer)": "capacitance_tandelta_transformer",
    "Capacitance & Tan Delta Comparison": "tandelta_comparison",
    # Current Transformer
    "CT Insulation Test": "ct_insulation_test",
    "CT Ratio Test (Detailed)": "ct_ratio_test_detailed",
    "Capacitance & Tan Delta Test (CT)": "capacitance_tandelta_ct",
    "Tan Delta NCT Test": "tandelta_nct",
    # CVT
    "CVT Test Report": "cvt_test",

    # ── DFR / IDAX (multi-session, cross-session comparison) ──
    "Dielectric Frequency Response (DFR / IDAX)": "dfr_idax_transformer",
    "DFR / IDAX":                                 "dfr_idax_transformer",

    # ── Tan-Delta / Capacitance / IDAX (single-session, individual + combined) ──
    "Tan-Delta, Capacitance & Insulation Diagnostics": "tan_delta_capacitance_idax",
    "Winding Tan-Delta & Capacitance Test":            "tan_delta_winding",
    "220kV Bushing Tan-Delta Test":                    "tan_delta_bushing_220kv",
    "66kV Bushing Tan-Delta Test":                     "tan_delta_bushing_66kv",
    "Insulation Diagnostics (IDAX)":                   "idax_insulation",

    # ── SFRA (multi-session, cross-session comparison) ──
    "Sweep Frequency Response Analysis (SFRA)":   "sfra_transformer",
    "SFRA":                                       "sfra_transformer",

    # ── Single-session routine DFR / SFRA (no factory baseline) ──
    "Dielectric Frequency Response (DFR) — Routine":        "dfr_routine",
    "Sweep Frequency Response Analysis (SFRA) — Routine":   "sfra_routine",

    # ── Oil test ──
    "Transformer Oil Test":             "transformer_oil_test",
    "Insulating Oil Test":              "transformer_oil_test",
    "Oil BDV Test":                     "transformer_oil_test",

    # ── DGA ──
    "Transformer Dissolved Gas Analysis (DGA)": "transformer_dga",
    "Dissolved Gas Analysis":                   "transformer_dga",
    "DGA Test":                                 "transformer_dga",

    # ── Calibration test types (enable_calibration=True, DATE_ADD rule) ──
    "Protection Relay Calibration and History": "protection_relay_calibration",
    "Electronic Tri-vector Meter Calibration":  "tri_vector_meter_calibration",

    # ── Cumulative operations test types (enable_cumulative=True, CUMULATIVE_DIFF rule) ──
    "Circuit Breaker Operations Count": "circuit_breaker_operations",
    "OLTC Operations Count":            "oltc_operations",

    # ── Circuit Breaker test types ──
    "Contact Resistance Test":               "circuit_breaker_contact_resistance",
    "Insulation Resistance Test":            "circuit_breaker_insulation_resistance",
    "SF6 Gas Pressure Test":                 "circuit_breaker_sf6_pressure",
    "SF6 Gas Purity Test":                   "circuit_breaker_sf6_purity",
    "Travel and Timing Test":                "circuit_breaker_travel_timing",
    "Minimum Trip Voltage Test":             "circuit_breaker_min_trip_voltage",

    # ── Surge Arrestor test types ──
    "Insulation Resistance / Leakage Current Test": "surge_arrestor_ir_leakage",
    "V-I Characteristic Test":               "surge_arrestor_vi_characteristic",
    "Power Frequency Voltage Withstand Test":"surge_arrestor_power_freq_withstand",

    # ── Battery Set test types ──
    "Specific Gravity Check":     "battery_specific_gravity",
    "Float Voltage per Cell":     "battery_float_voltage",
    "Discharge / Capacity Test":  "battery_discharge_capacity",
    "Electrolyte Level Check":    "battery_electrolyte_level",
    "Terminal Voltage Measurement":"battery_terminal_voltage",

    # ── Maintenance types ──
    "Routine Preventive Maintenance":       "transformer_maintenance",
    "Power Transformer Major Maintenance":  "transformer_maintenance",
    "Circuit Breaker Major Maintenance":    "circuit_breaker_maintenance",
    "Routine Battery Maintenance":          "battery_maintenance",
    "Battery Bank Major Maintenance":       "battery_maintenance",
    "Routine Visual Inspection":            "surge_arrestor_maintenance",
    "LA Major Maintenance":                 "surge_arrestor_maintenance",

    # ── Inspection types — equipment-specific ──
    # Power Transformer inspections → transformer_inspection
    "Electrical Safety":    "transformer_inspection",
    "Civil":                "transformer_inspection",
    "Fire Safety":          "transformer_inspection",
    "Documentation":        "transformer_inspection",
    "Environmental":        "transformer_inspection",
    "General Maintenance":  "transformer_inspection",

}


def get_template_for_test_type(test_type_name: str):
    """Look up a template by CategoryDetails.name (test type name)."""
    key = TEST_TYPE_TO_TEMPLATE.get(test_type_name)
    if key:
        return TEST_TEMPLATES.get(key)
    return None


def get_template_by_key(template_key: str):
    """Look up a template by its unique key."""
    return TEST_TEMPLATES.get(template_key)


# ── Row-identifier normalization ──────────────────────────────────────────
# winding_test_results / idax_test_results row identifiers ("test_configuration"
# column) are free text. Historical/legacy data commonly uses the classic
# capacitance-bridge codes (CHG, CHL, ...) instead of this template's default
# row names (HV-GND, HV-LV, ...) for the same physical measurement point,
# which fragments trend history since ParameterAnalytics keys on the raw
# row_id. Import paths should normalize through this before writing test_data.
#
# "MV" is treated as an alias for the LV (secondary) winding node -- some
# older reports use HV/MV/TV nomenclature where MV is explicitly the same
# physical 66kV winding other reports call LV (e.g. an annotated "HV-MV
# (HV=220kV,MV=66kV,TV=11kV)" row). "IV" is intentionally NOT merged into
# LV here: some reports test HV-IV/IV-LV/IV-GND as genuinely distinct rows
# alongside HV-LV/LV-TV/etc (an autotransformer intermediate-voltage node),
# matching this codebase's existing PDF extractor which already keeps IV
# rows on their own canonical labels (see _WINDING_CFG_PATTERNS_IV in
# seed_tandelta_from_pdf.py) rather than folding them into LV.
import re as _re

_ROW_ID_ALIASES: list[tuple[str, "_re.Pattern"]] = [
    ("HV-GND",      _re.compile(r"^(?:CHG|HV\s*[-–&]\s*(?:GND|Grd|Grnd|Ground))$", _re.I)),
    ("HV-LV",       _re.compile(r"^(?:CHL|HV\s*[-–&]\s*(?:LV|MV))$", _re.I)),
    ("LV-GND",      _re.compile(r"^(?:CLG|(?:LV|MV)\s*[-–]\s*(?:GND|Grd|Grnd|Ground))$", _re.I)),
    ("LV-TV",       _re.compile(r"^(?:CLT|(?:LV|MV)\s*[-–]\s*TV)$", _re.I)),
    ("TV-GND",      _re.compile(r"^(?:CTG|TV\s*[-–]\s*(?:GND|Grd|Grnd|Ground))$", _re.I)),
    ("HV-TV",       _re.compile(r"^(?:CTH|(?:HV|TV)\s*[-–]\s*(?:TV|HV))$", _re.I)),
    ("(HV+LV)-GND", _re.compile(r"^\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*(?:GND|Grd|Grnd|Ground)$", _re.I)),
    ("(HV+LV)-TV",  _re.compile(r"^\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*TV$", _re.I)),
]


_TRAILING_VOLTAGE_NOTE = _re.compile(r"\s*\([^()]*=[^()]*\)\s*$")


def normalize_row_id(raw: str) -> str:
    """
    Map a legacy/alternate row-identifier spelling (CHG, HV-Ground, ...) to
    this template's canonical row name (HV-GND, ...). Already-canonical
    values match themselves and pass through unchanged; anything unrecognized
    (custom rows a user added) is returned as-is.
    """
    text = (raw or "").strip()
    # Some reports append a trailing voltage-mapping note, e.g.
    # "HV-MV (HV=220kV,MV=66kV,TV=11kV)" - strip it before matching so the
    # underlying "HV-MV" still resolves. Only strips a trailing "(...)" that
    # contains "=" (a note), never a structural prefix like "(HV+LV)-GND".
    stripped = _TRAILING_VOLTAGE_NOTE.sub("", text)
    for canonical, pattern in _ROW_ID_ALIASES:
        if pattern.match(stripped):
            return canonical
    return raw
