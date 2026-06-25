"""
Validation service for Tan Delta & Capacitance test data
Provides data quality checks and error reporting
"""

from typing import Dict, List, Tuple, Optional


class TanDeltaValidator:
    """Validate tan delta test data for consistency and completeness"""
    
    # Valid ranges for typical transformer tests
    CAPACITANCE_RANGES = {
        "bushing": (50, 20000),      # pF - typical bushing capacitance
        "winding": (100, 50000),     # pF - typical winding capacitance
    }
    
    TANDELTA_RANGES = {
        "normal": (0.01, 0.5),       # % - normal operating range
        "high": (0.5, 2.0),          # % - elevated but acceptable
        "critical": (2.0, 10.0),     # % - needs investigation
    }
    
    VOLTAGE_RANGES = (0.5, 150)  # kV - 0.5kV to 150kV typical
    
    @staticmethod
    def validate_capacitance(value: float, data_type: str = "bushing") -> Tuple[bool, Optional[str]]:
        """Validate capacitance value"""
        if not value or value <= 0:
            return False, "Capacitance must be positive"
        
        min_val, max_val = TanDeltaValidator.CAPACITANCE_RANGES.get(
            data_type, (0, float('inf'))
        )
        
        if value < min_val or value > max_val:
            return False, f"Capacitance {value} pF outside typical {data_type} range ({min_val}-{max_val} pF)"
        
        return True, None
    
    @staticmethod
    def validate_tandelta(value: float) -> Tuple[bool, Optional[str]]:
        """Validate tan delta value"""
        if not value or value < 0:
            return False, "Tan delta must be non-negative"
        
        if value < TanDeltaValidator.TANDELTA_RANGES["normal"][0]:
            return True, f"Tan delta {value}% is unusually low - verify measurement"
        
        if value > TanDeltaValidator.TANDELTA_RANGES["normal"][1]:
            return True, f"Tan delta {value}% is elevated - may indicate insulation aging"
        
        return True, None
    
    @staticmethod
    def validate_voltage(value: float) -> Tuple[bool, Optional[str]]:
        """Validate test voltage"""
        min_val, max_val = TanDeltaValidator.VOLTAGE_RANGES
        
        if not value or value <= 0:
            return False, "Test voltage must be positive"
        
        if value < min_val or value > max_val:
            return False, f"Test voltage {value} kV outside range ({min_val}-{max_val} kV)"
        
        return True, None
    
    @staticmethod
    def validate_row(row: Dict) -> Dict:
        """Comprehensive validation of a single data row"""
        errors = []
        warnings = []
        details = {}
        
        # Validate configuration
        if row.get("winding_pair"):
            details["config"] = row["winding_pair"]
        elif row.get("bushing_type"):
            details["config"] = row["bushing_type"]
        else:
            errors.append("Neither winding_pair nor bushing_type provided")
        
        # Validate capacitance
        if row.get("cap_pf"):
            data_type = "winding" if row.get("winding_pair") else "bushing"
            is_valid, warning = TanDeltaValidator.validate_capacitance(
                float(row["cap_pf"]), data_type
            )
            if not is_valid:
                errors.append(warning)
            elif warning:
                warnings.append(warning)
            details["capacitance"] = f"{row['cap_pf']} pF"
        else:
            errors.append("Capacitance value missing")
        
        # Validate tan delta
        if row.get("tandelta_pct") is not None:
            is_valid, warning = TanDeltaValidator.validate_tandelta(float(row["tandelta_pct"]))
            if not is_valid:
                errors.append(warning)
            elif warning:
                warnings.append(warning)
            details["tandelta"] = f"{row['tandelta_pct']}%"
        else:
            errors.append("Tan delta value missing")
        
        # Validate test voltage
        if row.get("test_voltage_kv"):
            is_valid, warning = TanDeltaValidator.validate_voltage(float(row["test_voltage_kv"]))
            if not is_valid:
                errors.append(warning)
            elif warning:
                warnings.append(warning)
            details["voltage"] = f"{row['test_voltage_kv']} kV"
        else:
            warnings.append("Test voltage not specified")
        
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "details": details
        }
    
    @staticmethod
    def validate_test_data(test_data: Dict) -> Dict:
        """Validate complete test data structure"""
        report = {
            "overall_valid": True,
            "tables": {},
            "missing_sections": [],
            "row_count": 0,
            "error_count": 0,
            "warning_count": 0,
        }
        
        # List of expected table sections
        expected_sections = [
            "hv_bushing_readings",
            "lv_bushing_readings",
            "winding_ust_readings",
            "winding_gst_readings",
            "neutral_bushing"
        ]
        
        for section in expected_sections:
            if section not in test_data or not test_data[section]:
                report["missing_sections"].append(section)
                continue
            
            rows = test_data[section]
            if not isinstance(rows, list):
                continue
            
            section_report = {
                "row_count": len(rows),
                "rows": []
            }
            
            for idx, row in enumerate(rows):
                row_validation = TanDeltaValidator.validate_row(row)
                section_report["rows"].append({
                    "index": idx,
                    **row_validation
                })
                
                if not row_validation["is_valid"]:
                    report["error_count"] += 1
                    report["overall_valid"] = False
                
                report["warning_count"] += len(row_validation["warnings"])
            
            report["tables"][section] = section_report
            report["row_count"] += len(rows)
        
        return report
