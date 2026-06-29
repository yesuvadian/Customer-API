"""
PDF Extraction Logic for Tan Delta & Capacitance Tests
Handles pattern matching and text extraction from PDFs
"""

import re
from typing import Dict, List, Optional, Tuple


class TanDeltaExtractor:
    """Extract tan delta and capacitance data from PDFs"""
    
    # Configuration patterns to match
    WINDING_CONFIGS = {
        r"HV-IV|HV-iv|HV_IV": "HV-IV",
        r"HV-GND|HV-gnd|HV-Ground|HV-ground|HV_GND|HV_GROUND": "HV-GND",
        r"IV-LV|IV-lv|IV_LV": "IV-LV",
        r"IV-GND|IV-gnd|IV-Ground|IV-ground|IV_GND|IV_GROUND": "IV-GND",
        r"LV-GND|LV-gnd|LV-Ground|LV-ground|LV_GND|LV_GROUND": "LV-GND",
        r"HV-LV|HV-lv|HV_LV": "HV-LV",
        r"LV-TV|LV-tv|LV_TV": "LV-TV",
        r"TV-GND|TV-gnd|TV-Ground|TV-ground|TV_GND|TV_GROUND": "TV-GND",
        r"HV-TV|HV-tv|HV_TV": "HV-TV",
        r"IV-TV|IV-tv|IV_TV": "IV-TV",
    }
    
    BUSHING_TYPES = {
        r"^R\s*Phase|^R-Phase|^R_Phase": "R Phase",
        r"^Y\s*Phase|^Y-Phase|^Y_Phase": "Y Phase",
        r"^B\s*Phase|^B-Phase|^B_Phase": "B Phase",
        r"HV-Phase|HV-phase|HV_Phase": "HV-Phase",
        r"HV-Ground|HV-ground|HV_Ground|HV_GROUND": "HV-Ground",
        r"HV-Neutral|HV-neutral|HV_Neutral|Neutral": "HV-Neutral",
    }
    
    @staticmethod
    def normalize_config(text: str, config_type: str = "winding") -> Optional[str]:
        """Normalize configuration text to standard format"""
        if not text or not isinstance(text, str):
            return None
        
        text = text.strip()
        
        if config_type == "winding":
            patterns = TanDeltaExtractor.WINDING_CONFIGS
        elif config_type == "bushing":
            patterns = TanDeltaExtractor.BUSHING_TYPES
        else:
            return None
        
        for pattern, normalized in patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                return normalized
        
        return None
    
    @staticmethod
    def extract_voltage(text: str) -> Optional[float]:
        """Extract voltage value from text"""
        if not text or not isinstance(text, str):
            return None
        
        text = str(text).strip()
        match = re.search(r"(\d+\.?\d*)\s*(?:kV|KV|k|K)", text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (ValueError, IndexError):
                pass
        
        return None
    
    @staticmethod
    def extract_table_rows(table_data: List[Dict]) -> List[Dict]:
        """Process extracted table rows and normalize configurations"""
        if not table_data:
            return []
        
        processed_rows = []
        
        for row in table_data:
            processed_row = row.copy()
            
            # Normalize winding_pair if present
            if "winding_pair" in row and row["winding_pair"]:
                normalized = TanDeltaExtractor.normalize_config(
                    str(row["winding_pair"]), "winding"
                )
                if normalized:
                    processed_row["winding_pair"] = normalized
            
            # Normalize bushing_type if present
            if "bushing_type" in row and row["bushing_type"]:
                normalized = TanDeltaExtractor.normalize_config(
                    str(row["bushing_type"]), "bushing"
                )
                if normalized:
                    processed_row["bushing_type"] = normalized
            
            # Extract and normalize test voltage
            if "test_voltage_kv" in row and row["test_voltage_kv"]:
                voltage = TanDeltaExtractor.extract_voltage(
                    str(row["test_voltage_kv"])
                )
                if voltage:
                    processed_row["test_voltage_kv"] = voltage
            
            # Convert numeric strings to floats
            for field in ["cap_pf", "tandelta_pct", "tandelta_temp_corrected", "current_ma", "freq_hz"]:
                if field in row and row[field]:
                    try:
                        processed_row[field] = float(row[field])
                    except (ValueError, TypeError):
                        pass
            
            processed_rows.append(processed_row)
        
        return processed_rows
    
    @staticmethod
    def validate_row(row: Dict) -> Tuple[bool, List[str]]:
        """Validate a single row for missing critical data"""
        errors = []
        
        # Check for configuration (winding_pair OR bushing_type)
        if not row.get("winding_pair") and not row.get("bushing_type"):
            errors.append("Missing winding_pair or bushing_type")
        
        # Check for capacitance
        if row.get("cap_pf") is None:
            errors.append("Missing capacitance (cap_pf)")
        
        # Check for tan delta
        if row.get("tandelta_pct") is None:
            errors.append("Missing tan delta (tandelta_pct)")
        
        return len(errors) == 0, errors
