==========================================
Community MariaDB Collection Release Notes
==========================================

.. contents:: Topics

This changelog describes changes after version 2.0.0.

v6.0.3
======

Release Summary
---------------

This is a patch release of the ``ansible.mariadb`` collection.
This changelog contains all changes to the modules and plugins in this collection
that have been made after the previous release.

Bugfixes
--------

- mariadb_db - mask login password in ``executed_commands`` return value to prevent credential leakage in registered variables.
- mariadb_replication - mask primary password in ``executed_queries`` return value to prevent credential leakage in registered variables.
- mariadb_user - handle updating existing users when the password_lifetime attribute is missing from mysql.global_priv.priv

v6.0.2
======

Release Summary
---------------

This is a patch release of the ansible.mariadb collection. It only contains documentation fixes.

v6.0.1
======

Release Summary
---------------

This is a patch release of the ansible.mariadb collection. It only contains fixes of broken links in README.

v6.0.0
======

Release Summary
---------------

This is the first release of the `ansible.mariadb` collection.
This collection was cloned from the `ansible.mysql` collection to allow its contributors and maintainers to focus on MariaDB-related automation development.
MySQL is NOT supported by the `ansible.mariadb` collection.

Major Changes
-------------

- The mysql_clone, mysql_resource_group, and mysql_resource_group_info have been removed from the `ansible.mariadb` collection because they do not support MariaDB.
- This `ansible.mariadb` collection only supports MariaDB. Please do NOT use this collection for MySQL automation - use the `ansible.mysql` collection instead.

Prior changes
=============

This changelog contains items post collection split with ansible.mysql.
For older changes, cosult this changelog: https://github.com/ansible-collections/ansible.mysql/blob/main/CHANGELOG.rst#v510
