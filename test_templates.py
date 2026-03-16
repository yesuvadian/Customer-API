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
                            {"key": "pi_value", "label": "PI", "type": "number"},
                            {"key": "row_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"]}
                        ]
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
}


# ─── Test Type Name → Template Key Lookup ──────────────────────
TEST_TYPE_TO_TEMPLATE = {
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
    "Insulation resistance test": "insulation_resistance_test",  # reuses IR template
    "Transformer ratio test": "transformer_ratio_test",
    "Current ratio test": "current_ratio_test",
    "Short circuit test": "short_circuit_test",
    "Open circuit test": "open_circuit_test",
    "Magnetic balance test": "magnetic_balance_test",
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
