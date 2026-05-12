# Vendor Performance Evaluation Design

## 1. Overview

This document defines how vendor (manufacturer) performance will be evaluated using existing system data from:

- equipment
- testing_requests
- test_results

The system computes vendor scores based on reliability, quality, and service metrics.

---

## 2. Vendor Identification

### Current Approach
Vendor is derived from:

equipment.manufacturer

### Rules
- Vendor must always be derived from equipment
- Do NOT use testing_requests.manufacturer for evaluation

### Recommendation (Controlled Vendor List)

CREATE TABLE vendors (
    name varchar(255) PRIMARY KEY
);

ALTER TABLE equipment
ADD CONSTRAINT fk_equipment_vendor_name
FOREIGN KEY (manufacturer) REFERENCES vendors(name);

---

## 3. Data Flow

equipment → testing_requests → test_results

---

## 4. Evaluation Parameters

### 4.1 Failure Rate

SELECT 
    manufacturer,
    COUNT(*) FILTER (WHERE replacement_reason_type = 'FAILURE') AS failures
FROM equipment
GROUP BY manufacturer;

### 4.2 Inspection Pass Rate

SELECT 
    e.manufacturer,
    COUNT(*) FILTER (WHERE tr.pass_fail = 'PASS') * 100.0 / COUNT(*) AS pass_rate
FROM test_results tr
JOIN testing_requests t ON tr.testing_request_id = t.id
JOIN equipment e ON t.equipment_id = e.id
GROUP BY e.manufacturer;

---

## 5. Vendor Score Formula

Vendor Score =
    (W1 × Failure Score) +
    (W2 × Pass Rate) +
    (W3 × Design Score) +
    (W4 × Response Score) +
    (W5 × Quality Score)

---

## 6. Next Steps

- Standardize vendor names
- Add structured issue fields
- Implement scoring engine
- Build reporting dashboard
