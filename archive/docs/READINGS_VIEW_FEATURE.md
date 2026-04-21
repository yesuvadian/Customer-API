# Feature: View Previously Entered Test Data

**Issue**: Users cannot see what data was entered in previous test results  
**Request**: TR-20260421-0005  
**Date**: 2026-04-21

---

## Problems Identified

### 1. Database Issue (FIXED ✓)
- **Problem**: Test results had `test_session_id = NULL`
- **Cause**: Sessions incorrectly marked as "completed" instead of "in_progress"
- **Impact**: `_getCurrentSessionId()` returned NULL → results not linked to sessions
- **Fix Applied**: 
  - Set Session 1 status = 'in_progress'
  - Linked existing test result to Session 1
  - Deleted duplicate Session 2
  
### 2. UI Issue (NEEDS FIX)
- **Problem**: No way to VIEW previously entered test data
- **Current State**: Can only see template name and timestamp
- **User Need**: Click on a result to see all entered field values
  
---

## Solution: Add "View Details" Feature

### Backend (Already Exists ✓)

**Endpoint**: `GET /testing/{request_id}/results`

Returns test results with full `test_data` JSON:
```json
{
  "id": "uuid",
  "template_key": "ct_ratio_test_detailed",
  "test_data": {
    "primary_current": "100",
    "secondary_current": "5",
    "ratio": "20:1",
    "accuracy_class": "0.5"
  },
  "overall_result": "Pass",
  "evaluation_result": {...},
  "tested_at": "2026-04-21T15:57:26",
  "test_session_id": "uuid"
}
```

### Flutter UI Changes Needed

#### Option 1: Add "View" Button (Recommended)
Add a view icon button next to Edit/Delete in reading cards:

```dart
// In test_session_page.dart _buildReadingCard()

IconButton(
  icon: const Icon(Icons.visibility, size: 18),
  tooltip: 'View Details',
  onPressed: () => _showReadingDetails(reading),
),
```

#### Option 2: Make Card Clickable
Wrap entire card in GestureDetector:

```dart
GestureDetector(
  onTap: () => _showReadingDetails(reading),
  child: Card(...),
)
```

### Dialog to Display Data

```dart
void _showReadingDetails(Map<String, dynamic> reading) {
  showDialog(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(reading['template_label'] ?? 'Test Result'),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildDetailRow('Template', reading['template_key']),
            _buildDetailRow('Result', reading['overall_result']),
            _buildDetailRow('Tested At', _formatDate(reading['tested_at'])),
            const Divider(),
            const Text('Test Data:', 
              style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            ...(_buildTestDataFields(reading['test_data'])),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Close'),
        ),
        TextButton(
          onPressed: () {
            Navigator.pop(ctx);
            _showEditReadingDialog(reading, sessionId, prov);
          },
          child: const Text('Edit'),
        ),
      ],
    ),
  );
}

List<Widget> _buildTestDataFields(Map<String, dynamic>? testData) {
  if (testData == null || testData.isEmpty) {
    return [const Text('No test data')];
  }
  
  return testData.entries.map((entry) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 2,
            child: Text(
              _formatFieldName(entry.key),
              style: const TextStyle(fontWeight: FontWeight.w500),
            ),
          ),
          Expanded(
            flex: 3,
            child: Text(
              entry.value?.toString() ?? '-',
              style: const TextStyle(color: Colors.grey),
            ),
          ),
        ],
      ),
    );
  }).toList();
}

String _formatFieldName(String key) {
  // Convert snake_case to Title Case
  return key
      .split('_')
      .map((word) => word[0].toUpperCase() + word.substring(1))
      .join(' ');
}

Widget _buildDetailRow(String label, String? value) {
  return Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 100,
          child: Text(
            '$label:',
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ),
        Expanded(
          child: Text(value ?? '-'),
        ),
      ],
    ),
  );
}
```

---

## Implementation Steps

### Step 1: Update test_session_page.dart

Add view button to reading card:

```dart
Widget _buildReadingCard(
  Map<String, dynamic> reading,
  String sessionId,
  TestSessionProvider prov,
) {
  return Card(
    child: ListTile(
      title: Text("Reading #${reading['reading_number']}"),
      subtitle: Text(reading['template_label'] ?? reading['template_key']),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            icon: const Icon(Icons.visibility, size: 18),
            tooltip: 'View Details',
            onPressed: () => _showReadingDetails(reading, sessionId, prov),
          ),
          IconButton(
            icon: const Icon(Icons.edit, size: 18),
            tooltip: 'Edit',
            onPressed: () => _showEditReadingDialog(reading, sessionId, prov),
          ),
          IconButton(
            icon: const Icon(Icons.delete, size: 18),
            tooltip: 'Delete',
            onPressed: () => _confirmDeleteReading(reading, sessionId, prov),
          ),
        ],
      ),
    ),
  );
}
```

### Step 2: Add _showReadingDetails() Method

Copy the dialog code from above.

### Step 3: Update testing_detail.dart

Add similar view functionality for results shown in main testing details page.

Currently shows:
```dart
// Test Results section
CT Ratio Test (Detailed) - PASS
21/04/2026 15:57:26
[Enter Test Results] button
```

Should add click handler:
```dart
GestureDetector(
  onTap: () => _showResultDetails(result),
  child: ResultCard(...),
)
```

---

## Alternative: Use Test Result Form in Read-Only Mode

Instead of a simple dialog, open the actual form in read-only mode:

```dart
void _openResultForViewing(Map<String, dynamic> result) {
  RightPanelWrapper.show(
    context: context,
    width: 620,
    child: TestResultForm(
      requestId: widget.requestId,
      templateKey: result['template_key'],
      testTypeName: result['template_label'],
      testSessionId: result['test_session_id'],
      existingData: result['test_data'],  // Pre-fill form
      readOnly: true,  // New parameter
      onClose: () => Navigator.pop(context),
    ),
  );
}
```

This requires:
1. Add `readOnly` and `existingData` parameters to TestResultForm
2. Disable all form fields when readOnly=true
3. Pre-populate with existingData
4. Hide "Submit" button, show only "Close"

---

## Quick Fix for Current Issue

Since your test result is now linked to Session 1, you should see:

**After refresh**:
```
Testing Sessions (0 of 3 completed)

Session 1 - IN_PROGRESS
21 Apr 2026 15:56
Readings: 1

  Reading #1
  CT Ratio Test (Detailed) - PASS
  [👁 View] [✏ Edit] [🗑 Delete]
```

Click View → See all entered data fields

---

## Files to Modify

1. **lib/pages/zoho/test_session_page.dart**
   - Add `_showReadingDetails()` method
   - Add view icon button to `_buildReadingCard()`
   
2. **lib/pages/zoho/testing_detail.dart**
   - Make result cards clickable
   - Add `_showResultDetails()` method
   
3. **lib/pages/zoho/test_result_form.dart** (Optional)
   - Add `readOnly` parameter for view-only mode
   - Add `existingData` parameter for pre-filling

---

## Summary

✅ **Database Fixed**: Test result now linked to Session 1  
✅ **Session Status Fixed**: Session 1 set to 'in_progress'  
⏳ **UI Update Needed**: Add view functionality to see entered data  

**Next action**: Refresh Flutter app and verify Session 1 shows 1 reading
