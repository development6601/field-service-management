from rest_framework import serializers

from apps.attachments.models import Attachment, AttachmentType, RelatedEntityType
from apps.attachments.services import AttachmentService


class AttachmentUploadSerializer(serializers.ModelSerializer):
    """
    Intake serializer for uploading new files and linking them to domain entities.
    """

    file = serializers.FileField(required=True)
    attachment_type = serializers.ChoiceField(
        choices=AttachmentType.choices,
        default=AttachmentType.GENERAL,
        required=False,
    )
    related_entity_type = serializers.ChoiceField(
        choices=RelatedEntityType.choices,
        required=True,
    )
    related_entity_id = serializers.UUIDField(required=True)
    description = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )

    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id",
            "file",
            "file_name",
            "file_type",
            "file_size_bytes",
            "file_size_display",
            "attachment_type",
            "description",
            "related_entity_type",
            "related_entity_id",
            "uploaded_by",
            "download_url",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "file_name",
            "file_type",
            "file_size_bytes",
            "file_size_display",
            "uploaded_by",
            "download_url",
            "created_at",
        ]

    def validate(self, attrs):
        file_obj = attrs.get("file")
        clean_name, mime_type, file_size = AttachmentService.validate_file(file_obj)

        entity_type = attrs.get("related_entity_type")
        entity_id = attrs.get("related_entity_id")
        entity_obj = AttachmentService.resolve_entity(entity_type, entity_id)

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and not AttachmentService.check_user_access(user, entity_type, entity_obj):
            raise serializers.ValidationError(
                {"related_entity_id": "You do not have permission to attach files to this entity."}
            )

        attrs["_clean_name"] = clean_name
        attrs["_mime_type"] = mime_type
        attrs["_file_size"] = file_size
        return attrs

    def create(self, validated_data):
        clean_name = validated_data.pop("_clean_name", "")
        mime_type = validated_data.pop("_mime_type", "")
        file_size = validated_data.pop("_file_size", 0)

        request = self.context.get("request")
        user = getattr(request, "user", None)

        attachment = Attachment.objects.create(
            file_name=clean_name,
            file_type=mime_type,
            file_size_bytes=file_size,
            uploaded_by=user if user and user.is_authenticated else None,
            **validated_data,
        )
        return attachment

    def get_download_url(self, obj):
        request = self.context.get("request")
        url_path = f"/api/v1/attachments/{obj.id}/download/"
        if request:
            return request.build_absolute_uri(url_path)
        return url_path


class AttachmentListSerializer(serializers.ModelSerializer):
    """
    Read serializer for listing attachments in galleries, job cards, and invoices.
    """

    file_size_display = serializers.CharField(read_only=True)
    uploaded_by_name = serializers.CharField(source="uploaded_by.get_full_name", read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            "id",
            "file",
            "file_name",
            "file_type",
            "file_size_bytes",
            "file_size_display",
            "attachment_type",
            "description",
            "related_entity_type",
            "related_entity_id",
            "uploaded_by",
            "uploaded_by_name",
            "download_url",
            "created_at",
        ]
        read_only_fields = fields

    def get_download_url(self, obj):
        request = self.context.get("request")
        url_path = f"/api/v1/attachments/{obj.id}/download/"
        if request:
            return request.build_absolute_uri(url_path)
        return url_path
