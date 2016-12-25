from django.core import validators
from django.db import models
from netfields import CidrAddressField

from ssh_pam.exceptions import *


def can_be_disabled(cls):
    @classmethod
    def all_enabled(cls):
        return cls.objects.filter(enabled=True)

    def __str__(self):
        return "{}: {}".format(cls.__old__str__(self), ('DISABLED', 'ENABLED')[self.enabled])

    models.BooleanField(default=False).contribute_to_class(cls, 'enabled')

    cls.__old__str__ = cls.__str__
    cls.__str__ = __str__

    return cls


def inherit_disabled(parent_attr):
    def decorator(cls):
        @classmethod
        def all_enabled(cls):
            return cls.objects.filter(**{
                parent_attr + "__enabled": True
            })

        cls.all_enabled = all_enabled

        return cls

    return decorator


"""
AUTHENTICATION METHODS
"""


@can_be_disabled
class AuthenticationMethod(models.Model):
    name = models.CharField(max_length=128)

    def __str__(self):
        return self.name

    @staticmethod
    def all_enabled():
        return AuthenticationMethod.objects.filter(enabled=True)


@inherit_disabled('auth')
class LocalFileAuthenticationMethod(models.Model):
    auth = models.OneToOneField(
        AuthenticationMethod,
        on_delete=models.CASCADE,
        primary_key=True
    )
    file_path = models.CharField(max_length=255)

    def __str__(self):
        return "{} [file://{}]".format(self.auth, self.file_path)


@inherit_disabled('auth')
class LDAPAuthenticationMethod(models.Model):
    auth = models.OneToOneField(
        AuthenticationMethod,
        on_delete=models.CASCADE,
        primary_key=True
    )

    conn_uri = models.CharField(
        max_length=255,
        validators=[validators.URLValidator(schemes=["ldaps", "ldap"])]
    )
    base_dn = models.CharField(max_length=128)
    bind_user = models.CharField(max_length=128)
    bind_passwd = models.CharField(max_length=128)

    user_class = models.CharField(max_length=128, default="inetOrgPerson")
    group_class = models.CharField(max_length=128, default="posixGroup")
    member_attr = models.CharField(max_length=128, default="memberUid")

    def __str__(self):
        return "{} [{}]".format(self.auth, self.conn_uri)


"""
RULES
"""


class HostGroup(models.Model):
    name = models.CharField(max_length=128)
    cidr = CidrAddressField()
    port = models.SmallIntegerField(default=22)

    def __str__(self):
        return "{}: {}".format(self.name, self.cidr.exploded)


class TargetAcount(models.Model):
    name = models.CharField(max_length=128)
    username = models.CharField(max_length=128)
    passwd = models.CharField(max_length=128)

    def __str__(self):
        return "{}: {}".format(self.name, self.username)


class GroupMapping(models.Model):
    name = models.CharField(max_length=128)
    group = models.CharField(unique=True, max_length=255)
    target = models.ForeignKey(TargetAcount)

    def __str__(self):
        return "{}: {} - [{}]".format(
            self.name,
            self.group,
            self.target
        )


@can_be_disabled
class Rule(models.Model):
    name = models.CharField(max_length=128)
    hosts = models.ManyToManyField(HostGroup)
    groups = models.ManyToManyField(GroupMapping)
    preference = models.IntegerField(default=0)
    authenticator = models.ForeignKey(AuthenticationMethod)

    def __str__(self):
        return "{}: [{}] --> [{}]".format(
            self.name,
            ",".join(("<{}>".format(str(x)) for x in self.groups.all())),
            ",".join((str(x) for x in self.hosts.all()))
        )

    @staticmethod
    def get_matching_rule(target_ip):
        return Rule.objects.filter(
            hosts__cidr__net_contains_or_equals=target_ip
        ).order_by('-preference').first()

    def get_target_credentials(self, groups, target_ip):
        h = self.hosts.filter(cidr__net_contains_or_equals=target_ip).first()
        g = self.groups.filter(group__in=groups).first()

        if not g:
            raise NoGroupMappingException()

        return (g.target.username, g.target.passwd, h.port)