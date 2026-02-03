from rest_framework import serializers
from .models import ActionLog, ActionLogAssignmentHistory, ActionLogNotification, ActionLogComment
from users.serializers import UserSerializer
from departments.serializers import DepartmentSerializer
from departments.models import Department
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings

User = get_user_model()


class MinimalUserSerializer(serializers.ModelSerializer):
    """Minimal user representation for assignment history; avoids full UserSerializer and its delegation/approver logic."""
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'email']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance is None:
            return None
        if not data.get('email'):
            data['email'] = ''
        return data

class ActionLogSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    approved_by = UserSerializer(read_only=True)
    department = DepartmentSerializer(read_only=True)
    department_id = serializers.IntegerField(write_only=True)
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        required=True
    )
    team_leader = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True
    )
    can_approve = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()
    created_by_department_unit = serializers.SerializerMethodField()
    closure_requested_by = UserSerializer(read_only=True)
    original_assigner = serializers.SerializerMethodField()

    class Meta:
        model = ActionLog
        fields = [
            'id', 'title', 'description', 'department', 'department_id',
            'created_by', 'created_by_department_unit', 'status', 'priority', 
            'due_date', 'entry_date', 'assigned_to', 'team_leader', 'approved_by', 'approved_at', 
            'rejection_reason', 'created_at', 'updated_at', 'can_approve', 
            'comment_count', 'closure_approval_stage', 'closure_requested_by',
            'original_assigner', 'current_update'
        ]
        read_only_fields = [
            'created_by', 'approved_by', 'approved_at',
            'created_at', 'updated_at', 'comment_count',
            'closure_approval_stage', 'closure_requested_by', 'original_assigner'
        ]

    def get_can_approve(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.can_approve(request.user)
        return False

    def get_comment_count(self, obj):
        return obj.comments.count()

    def get_created_by_department_unit(self, obj):
        if obj.created_by and obj.created_by.department_unit:
            return {
                'id': obj.created_by.department_unit.id,
                'name': obj.created_by.department_unit.name
            }
        return None

    def get_original_assigner(self, obj):
        """Get the original assigner (first person to assign this action log)"""
        try:
            # Get the oldest assignment record (original assignment)
            original_assignment = obj.assignment_history.order_by('assigned_at').first()
            if original_assignment:
                return {
                    'id': original_assignment.assigned_by.id,
                    'first_name': original_assignment.assigned_by.first_name,
                    'last_name': original_assignment.assigned_by.last_name,
                    'email': original_assignment.assigned_by.email
                }
        except Exception as e:
            print(f"Error getting original assigner: {str(e)}")
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Default current_update to "No update yet" when empty (backend default)
        if not (data.get('current_update') or '').strip():
            data['current_update'] = 'No update yet'
        return data

    def create(self, validated_data):
        print(f"[SERIALIZER] create: Starting creation with validated_data: {validated_data}")
        request = self.context.get('request')
        if request and request.user:
            validated_data['created_by'] = request.user
            print(f"[SERIALIZER] create: Set created_by to user: {request.user.id}")
        
        # Extract assigned_to before creating the instance
        assigned_to = validated_data.pop('assigned_to', [])
        print(f"[SERIALIZER] create: Extracted assigned_to: {assigned_to}")
        
        # Extract team_leader if provided
        team_leader = validated_data.pop('team_leader', None)
        print(f"[SERIALIZER] create: Team leader: {team_leader}")
        
        # Get department from department_id
        department_id = validated_data.pop('department_id')
        print(f"[SERIALIZER] create: Department ID: {department_id}")
        try:
            department = Department.objects.get(id=department_id)
            validated_data['department'] = department
            print(f"[SERIALIZER] create: Found department: {department.name}")
        except Department.DoesNotExist:
            print(f"[SERIALIZER] create: Department not found: {department_id}")
            raise serializers.ValidationError({
                'department_id': f'Department with id {department_id} does not exist'
            })
        
        print(f"[SERIALIZER] create: Final validated_data: {validated_data}")
        
        # Create the action log instance
        instance = super().create(validated_data)
        print(f"[SERIALIZER] create: Created instance: {instance.id}")
        
        # Add the assigned users
        if assigned_to:
            instance.assigned_to.set(assigned_to)
            print(f"[SERIALIZER] create: Set assigned_to: {list(instance.assigned_to.values_list('id', flat=True))}")
        
        # Set the team_leader: use provided value or auto-select first assignee when 2+
        if team_leader:
            instance.team_leader = team_leader
        elif len(assigned_to) >= 2 and assigned_to:
            instance.team_leader = assigned_to[0]
        if instance.team_leader_id:
            instance.save(update_fields=['team_leader'])
        
        return instance

    def validate(self, data):
        print(f"[SERIALIZER] validate: Received data: {data}")
        print(f"[SERIALIZER] validate: Data keys: {list(data.keys())}")
        print(f"[SERIALIZER] validate: Data types: {[(k, type(v)) for k, v in data.items()]}")
        
        # Auto-select team leader when there are 2+ assignees: use first in list if not provided
        assigned_to = data.get('assigned_to', [])
        team_leader = data.get('team_leader')
        
        if len(assigned_to) >= 2:
            if not team_leader and assigned_to:
                data['team_leader'] = assigned_to[0]
                team_leader = assigned_to[0]
            # Ensure team leader is one of the assigned users when provided
            if team_leader and team_leader not in assigned_to:
                raise serializers.ValidationError({
                    'team_leader': 'Team leader must be one of the assigned users'
                })
        
        # Add any additional validation here
        if data.get('due_date') and data['due_date'] < timezone.now():
            print(f"[SERIALIZER] validate: Due date validation failed - due_date: {data['due_date']}, now: {timezone.now()}")
            raise serializers.ValidationError({
                'due_date': 'Due date cannot be in the past'
            })
        
        print(f"[SERIALIZER] validate: Validation passed")
        return data

class ActionLogApprovalSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        request = self.context.get('request')
        action_log = self.context.get('action_log')

        if not action_log.can_approve(request.user):
            raise serializers.ValidationError(
                "You don't have permission to approve/reject this action log"
            )

        return data

class ActionLogAssignmentHistorySerializer(serializers.ModelSerializer):
    assigned_by = MinimalUserSerializer(read_only=True)
    assigned_to = serializers.SerializerMethodField()

    class Meta:
        model = ActionLogAssignmentHistory
        fields = ['id', 'action_log', 'assigned_by', 'assigned_to', 'assigned_at', 'comment']
        read_only_fields = ['action_log', 'assigned_by', 'assigned_at']

    def get_assigned_to(self, obj):
        try:
            users = obj.get_assigned_to_users()
            return MinimalUserSerializer(users, many=True).data
        except Exception as e:
            return []

    def to_representation(self, instance):
        try:
            data = super().to_representation(instance)
            # Ensure assigned_by is null-safe (e.g. if FK was deleted despite PROTECT)
            if data.get('assigned_by') is None and instance.assigned_by_id:
                data['assigned_by'] = {'id': instance.assigned_by_id, 'first_name': '', 'last_name': '', 'email': ''}
            return data
        except Exception as e:
            # Defensive: return minimal data so the endpoint doesn't 500
            return {
                'id': instance.id,
                'action_log': instance.action_log_id,
                'assigned_by': {'id': getattr(instance, 'assigned_by_id', None), 'first_name': '', 'last_name': '', 'email': ''},
                'assigned_to': [],
                'assigned_at': str(instance.assigned_at) if hasattr(instance, 'assigned_at') else None,
                'comment': getattr(instance, 'comment', None) or '',
            }

class ActionLogNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionLogNotification
        fields = ['id', 'user', 'action_log', 'comment', 'is_read', 'created_at']
        read_only_fields = ['id', 'user', 'action_log', 'comment', 'is_read', 'created_at']

class ActionLogCommentSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    parent_id = serializers.IntegerField(write_only=True, required=False)
    status = serializers.CharField(read_only=True)
    is_current_update = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = ActionLogComment
        fields = ['id', 'action_log', 'user', 'comment', 'created_at', 'updated_at', 'parent_id', 'replies', 'status', 'is_current_update']
        read_only_fields = ['id', 'user', 'created_at', 'updated_at', 'status', 'is_current_update']

    def get_replies(self, obj):
        replies = obj.replies.all().select_related('user').order_by('created_at')
        return ActionLogCommentSerializer(replies, many=True).data

    def to_representation(self, instance):
        try:
            data = super().to_representation(instance)
            # Ensure all required fields are present
            if 'user' in data and not data['user'].get('email'):
                data['user']['email'] = ''
            if 'status' not in data:
                data['status'] = 'open'
            if 'is_approved' not in data:
                data['is_approved'] = False
            if 'is_viewed' not in data:
                data['is_viewed'] = False
            if 'is_current_update' not in data:
                data['is_current_update'] = getattr(instance, 'is_current_update', False)
            return data
        except Exception as e:
            print(f"Error serializing comment {instance.id}: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            raise 