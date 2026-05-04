from fastapi import HTTPException


class ValidationService:

    @staticmethod
    def validate_stage(template: dict, form_data: dict):
        errors = []

        sections = template.get("sections", [])

        for section in sections:
            for field in section.get("fields", []):

                key = field.get("key")
                field_type = field.get("type")
                required = field.get("required", False)

                value = form_data.get(key)

                # 1. Required check
                if required and not value:
                    errors.append(f"{key} is required")
                    continue

                if value is None:
                    continue  # skip further checks

                # 2. Type validation
                type_error = ValidationService.validate_type(field_type, value, field)
                if type_error:
                    errors.append(f"{key}: {type_error}")

        if errors:
            raise HTTPException(status_code=400, detail=errors)
        
    @staticmethod
    def validate_type(field_type, value, field):

        if field_type == "text":
            if not isinstance(value, str):
                return "must be a string"

        elif field_type == "number":
            if not isinstance(value, (int, float)):
                return "must be a number"

        elif field_type == "date":
            # assume ISO string
            if not isinstance(value, str):
                return "must be a valid date string"

        elif field_type == "select":
            options = field.get("options", [])
            if value not in options:
                return f"must be one of {options}"

        elif field_type == "file":
            # assume file already uploaded → expect URL or ID
            if not isinstance(value, str):
                return "invalid file reference"

        elif field_type == "textarea":
            if not isinstance(value, str):
                return "must be text"

        return None