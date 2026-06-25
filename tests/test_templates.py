"""
Test Result Templates — Template-driven dynamic forms for each test type.

Each template defines sections and fields that the Flutter UI renders dynamically.
Test results are stored as JSONB in a single test_results table.

Field types: text, number, dropdown, boolean, textarea, table
"""

TEST_TEMPLATES = {
    # ────────────────────────────────────────────────────────────
    # 1. Relay Testing Report (Feeder protection relays)
    # ────────────────────────────────────────────────────────────
    "relay_testing_report": {
        "key": "relay_testing_report",
        "name": "Relay Testing Report",
        "equipment_type": "Feeder protection relays",
        "description": "Complete relay testing report with overcurrent and earth fault tests",
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
                    {"key": "oc_phase_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "required": True},
                ]
            },
            {
                "title": "Earth Fault Test",
                "fields": [
                    {"key": "ef_pickup", "label": "EF Pickup Current (Set)", "type": "number", "unit": "A", "required": True},
                    {"key": "ef_pickup_actual", "label": "EF Pickup Current (Actual)", "type": "number", "unit": "A", "required": True},
                    {"key": "ef_tms", "label": "EF TMS Setting", "type": "number"},
                    {"key": "ef_operating_time", "label": "EF Operating Time", "type": "number", "unit": "sec"},
                    {"key": "ef_result", "label": "EF Test Result", "type": "dropdown", "options": ["Pass", "Fail"], "required": True},
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                            {"key": "relay_operation", "label": "Relay Op.", "type": "dropdown", "options": ["Trip", "No Trip"]},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
        "equipment_type": "Protection relays",
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
        "equipment_type": "Current transformers",
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
        "equipment_type": "Current transformers",
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
        "equipment_type": "Current transformers",
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
        "sections": [
            {
                "title": "Transformer Identification",
                "fields": [
                    {"key": "transformer_make", "label": "Transformer Make", "type": "text", "required": True},
                    {"key": "transformer_serial", "label": "Serial Number", "type": "text", "required": True},
                    {"key": "transformer_rating", "label": "Rating", "type": "text", "placeholder": "e.g. 100 kVA"},
                    {"key": "location", "label": "Installation Location", "type": "text"},
                ]
            },
            {
                "title": "External Condition",
                "fields": [
                    {"key": "body_condition", "label": "Body/Tank Condition", "type": "dropdown", "options": ["Good", "Fair", "Poor", "Damaged"], "required": True},
                    {"key": "paint_condition", "label": "Paint Condition", "type": "dropdown", "options": ["Good", "Faded", "Peeling", "Rusted"], "required": True},
                    {"key": "oil_leak", "label": "Oil Leakage Observed", "type": "boolean", "required": True},
                    {"key": "oil_leak_location", "label": "Leakage Location", "type": "text"},
                    {"key": "oil_level", "label": "Oil Level", "type": "dropdown", "options": ["Normal", "Low", "Very Low", "Empty"], "required": True},
                    {"key": "oil_color", "label": "Oil Color", "type": "dropdown", "options": ["Clear", "Light Yellow", "Dark Yellow", "Brown", "Black"]},
                    {"key": "silica_gel_condition", "label": "Silica Gel Condition", "type": "dropdown", "options": ["Blue (Good)", "Pink (Saturated)", "Not Available"]},
                ]
            },
            {
                "title": "Bushings & Connections",
                "fields": [
                    {"key": "hv_bushing_condition", "label": "HV Bushing Condition", "type": "dropdown", "options": ["Good", "Cracked", "Chipped", "Damaged"], "required": True},
                    {"key": "lv_bushing_condition", "label": "LV Bushing Condition", "type": "dropdown", "options": ["Good", "Cracked", "Chipped", "Damaged"], "required": True},
                    {"key": "terminal_connections", "label": "Terminal Connections", "type": "dropdown", "options": ["Tight", "Loose", "Corroded"], "required": True},
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "max_deviation", "label": "Max Deviation", "type": "number", "unit": "%"},
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
                        ]
                    }
                ]
            },
            {
                "title": "Overall Assessment",
                "fields": [
                    {"key": "max_imbalance", "label": "Max Imbalance", "type": "number", "unit": "%"},
                    {"key": "overall_remarks", "label": "Remarks", "type": "textarea"},
                    {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "options": ["Pass", "Fail", "Conditional", "Retest"], "required": True},
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
        "equipment_type": "Meter",
        "description": "Testing of energy meters at substations",
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
                ]
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
        "equipment_type": "Relay",
        "description": "Testing of relays at substations with phase-wise readings",
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
                ]
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
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "location", "label": "Location of the Transformer", "type": "text", "required": True},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
                ]
            },
            {
                "title": "Transformer Nameplate Details",
                "fields": [
                    {"key": "make", "label": "Make", "type": "text", "required": True},
                    {"key": "tr_class", "label": "Class", "type": "text"},
                    {"key": "rated_mva", "label": "Rated MVA", "type": "text", "required": True},
                    {"key": "rated_voltage", "label": "Rated Voltage", "type": "text"},
                    {"key": "rated_current", "label": "Rated Current", "type": "text"},
                    {"key": "rated_insulation", "label": "Rated Insulation", "type": "text"},
                    {"key": "frequency", "label": "Frequency", "type": "text"},
                    {"key": "phases_hv_iv_lv", "label": "Phases HV/IV/LV", "type": "text"},
                    {"key": "vector_group", "label": "Vector Group", "type": "text"},
                    {"key": "impedance_voltage", "label": "Impedance Voltage", "type": "text"},
                    {"key": "sl_no", "label": "Serial Number", "type": "text"},
                    {"key": "type_of_cooling", "label": "Type of Cooling", "type": "text"},
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
                    {"key": "yom", "label": "Year of Manufacture", "type": "text"},
                    {"key": "taps_on_hv", "label": "Taps available on HV", "type": "text"},
                    {"key": "specification", "label": "Specification", "type": "text"},
                    {"key": "date_of_commission", "label": "Date of Commission", "type": "date"},
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
        "sections": [
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
        "sections": [
            {
                "title": "CT Details",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "bay_name", "label": "Bay Name", "type": "text", "required": True},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
                    {"key": "ct_make", "label": "Make", "type": "text"},
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
                    {"key": "ct_sl_no", "label": "Serial Number", "type": "text"},
                    {"key": "ct_yom", "label": "Year of Manufacture", "type": "text"},
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
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "bay_name", "label": "Bay Name", "type": "text", "required": True},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
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
        "equipment_type": "CVT",
        "description": "CVT test report with details, insulation resistance, and ratio test",
        "sections": [
            {
                "title": "CVT Details",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "bay_name", "label": "Bay Name", "type": "text", "required": True},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
                    {"key": "cvt_make", "label": "Make", "type": "text"},
                    {"key": "core1_burden", "label": "Core 1 - Burden", "type": "text"},
                    {"key": "core1_class", "label": "Core 1 - Class", "type": "text"},
                    {"key": "core2_burden", "label": "Core 2 - Burden", "type": "text"},
                    {"key": "core2_class", "label": "Core 2 - Class", "type": "text"},
                    {"key": "core3_burden", "label": "Core 3 - Burden", "type": "text"},
                    {"key": "core3_class", "label": "Core 3 - Class", "type": "text"},
                    {"key": "insulation", "label": "Insulation", "type": "text"},
                    {"key": "cvt_type", "label": "Type", "type": "text"},
                    {"key": "cvt_yom", "label": "Year of Manufacture", "type": "text"},
                    {"key": "cvt_sl_no", "label": "Serial Number", "type": "text"},
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
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "bay_name", "label": "Bay Name", "type": "text"},
                    {"key": "ct_make", "label": "CT Make", "type": "text"},
                    {"key": "ct_sl_no", "label": "CT Serial No", "type": "text"},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
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
                        ]
                    }
                ]
            },
        ]
    },

    # ────────────────────────────────────────────────────────────
    # 37. Capacitance & Tan Delta Test Transformer (Power Transformer)
    # ────────────────────────────────────────────────────────────
    "capacitance_tandelta_transformer": {
        "key": "capacitance_tandelta_transformer",
        "name": "Capacitance & Tan Delta Test (Transformer)",
        "equipment_type": "Power Transformer",
        "description": "Capacitance and tan delta test results for transformer bushings and windings",
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "transformer_name", "label": "Transformer Name", "type": "text", "required": True},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
                    {"key": "test_voltage_kv", "label": "Test Voltage (kV)", "type": "number", "required": True},
                ]
            },
            {
                "title": "HV Bushing Readings",
                "fields": [
                    {"key": "hv_bushing_readings", "label": "HV Bushing Capacitance & Tan Delta", "type": "table", "columns": [
                        {"key": "bushing_type", "label": "Bushing Type", "type": "dropdown", "options": ["HV-Phase", "HV-Ground", "HV-Neutral", "R Phase", "Y Phase", "B Phase"], "required": True},
                        {"key": "freq_hz", "label": "f (Hz)", "type": "number"},
                        {"key": "test_voltage_kv", "label": "Test Voltage (kV)", "type": "number"},
                        {"key": "current_ma", "label": "I (mA)", "type": "number"},
                        {"key": "cap_pf", "label": "C (pF)", "type": "number"},
                        {"key": "tandelta_pct", "label": "%TanD", "type": "number"},
                        {"key": "tandelta_temp_corrected", "label": "%TanD (Temp Corrected)", "type": "number"},
                    ]}
                ]
            },
            {
                "title": "LV/IV Bushing Readings",
                "fields": [
                    {"key": "lv_bushing_readings", "label": "LV/IV Bushing Capacitance & Tan Delta", "type": "table", "columns": [
                        {"key": "bushing_type", "label": "Bushing Type", "type": "dropdown", "options": ["HV-Phase", "HV-Ground", "HV-Neutral", "R Phase", "Y Phase", "B Phase"], "required": True},
                        {"key": "freq_hz", "label": "f (Hz)", "type": "number"},
                        {"key": "test_voltage_kv", "label": "Test Voltage (kV)", "type": "number"},
                        {"key": "current_ma", "label": "I (mA)", "type": "number"},
                        {"key": "cap_pf", "label": "C (pF)", "type": "number"},
                        {"key": "tandelta_pct", "label": "%TanD", "type": "number"},
                        {"key": "tandelta_temp_corrected", "label": "%TanD (Temp Corrected)", "type": "number"},
                    ]}
                ]
            },
            {
                "title": "Winding Readings (UST)",
                "fields": [
                    {"key": "winding_ust_readings", "label": "Winding Capacitance & Tan Delta (UST)", "type": "table", "columns": [
                        {"key": "winding_pair", "label": "Winding Configuration", "type": "dropdown", "options": ["HV-IV", "HV-GND", "IV-LV", "IV-GND", "LV-GND", "HV-LV", "IV-TV", "LV-TV", "TV-GND", "HV-TV"], "required": True},
                        {"key": "test_voltage_kv", "label": "Test Voltage (kV)", "type": "number"},
                        {"key": "current_ma", "label": "I (mA)", "type": "number"},
                        {"key": "cap_pf", "label": "C (pF)", "type": "number"},
                        {"key": "tandelta_pct", "label": "%TanD", "type": "number"},
                        {"key": "tandelta_temp_corrected", "label": "%TanD (Temp Corrected)", "type": "number"},
                    ]}
                ]
            },
            {
                "title": "Winding Readings (GSTg-RB)",
                "fields": [
                    {"key": "winding_gst_readings", "label": "Winding Capacitance & Tan Delta (GSTg-RB)", "type": "table", "columns": [
                        {"key": "winding_pair", "label": "Winding Configuration", "type": "dropdown", "options": ["HV-IV", "HV-GND", "IV-LV", "IV-GND", "LV-GND", "HV-LV", "IV-TV", "LV-TV", "TV-GND", "HV-TV"], "required": True},
                        {"key": "test_voltage_kv", "label": "Test Voltage (kV)", "type": "number"},
                        {"key": "current_ma", "label": "I (mA)", "type": "number"},
                        {"key": "cap_pf", "label": "C (pF)", "type": "number"},
                        {"key": "tandelta_pct", "label": "%TanD", "type": "number"},
                        {"key": "tandelta_temp_corrected", "label": "%TanD (Temp Corrected)", "type": "number"},
                    ]}
                ]
            },
            {
                "title": "Neutral Bushing",
                "fields": [
                    {"key": "neutral_bushing", "label": "Neutral Bushing Readings", "type": "table", "columns": [
                        {"key": "bushing_type", "label": "Bushing Type", "type": "dropdown", "options": ["HV-Phase", "HV-Ground", "HV-Neutral", "R Phase", "Y Phase", "B Phase"], "required": True},
                        {"key": "freq_hz", "label": "f (Hz)", "type": "number"},
                        {"key": "test_voltage_kv", "label": "Test Voltage (kV)", "type": "number"},
                        {"key": "current_ma", "label": "I (mA)", "type": "number"},
                        {"key": "cap_pf", "label": "C (pF)", "type": "number"},
                        {"key": "tandelta_pct", "label": "%TanD", "type": "number"},
                        {"key": "tandelta_temp_corrected", "label": "%TanD (Temp Corrected)", "type": "number"},
                    ]}
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
        "sections": [
            {
                "title": "Test Information",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
                    {"key": "test_voltage_kv", "label": "Test Voltage (kV)", "type": "number", "required": True},
                ]
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
                        ]
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
        "sections": [
            {
                "title": "NCT Details",
                "fields": [
                    {"key": "station_name", "label": "Station Name", "type": "text", "required": True},
                    {"key": "nct_make", "label": "NCT Make", "type": "text"},
                    {"key": "nct_sl_no", "label": "NCT Serial No", "type": "text"},
                    {"key": "date_of_testing", "label": "Date of Testing", "type": "date", "required": True},
                ]
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
                        ]
                    }
                ]
            },
        ]
    },
}


# ─── Test Type Name → Template Key Lookup ──────────────────────
TEST_TYPE_TO_TEMPLATE = {
    # Existing mappings
    "Relay Testing Report": "relay_testing_report",
    "Differential Protection Test": "differential_protection_test",
    "Stability / Bias Test": "stability_bias_test",
    "Protection Relay Functional Test": "protection_relay_functional_test",
    "Insulation Resistance (IR) Test": "insulation_resistance_test",
    "CT Ratio Test": "ct_ratio_test",
    "Core Insulation Test": "core_insulation_test",
    "Transformer Protection Commissioning": "transformer_protection_commissioning",
    "Energy meter accuracy test": "energy_meter_accuracy_test",
    "Physical inspection": "physical_inspection",
    "Insulation resistance test": "insulation_resistance_test",
    "Transformer ratio test": "transformer_ratio_test",
    "Current ratio test": "current_ratio_test",
    "Short circuit test": "short_circuit_test",
    "Open circuit test": "open_circuit_test",
    "Magnetic balance test": "magnetic_balance_test",
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
