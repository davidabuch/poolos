# Buch IntelliCenter

A professionally maintained Home Assistant integration for Pentair IntelliCenter systems.

## Purpose

Buch IntelliCenter provides a stable hardware interface between Pentair IntelliCenter equipment and higher-level automation platforms.

Its responsibilities include:

- Communication with Pentair IntelliCenter
- Equipment state management
- Home Assistant entity creation
- Reliable local control
- Diagnostic reporting
- Stable APIs for automation

## Design Philosophy

This project intentionally separates equipment communication from automation logic.

Buch IntelliCenter is responsible for **how to communicate with the equipment**.

Pool Manager is responsible for **deciding what the equipment should do**.

Keeping these responsibilities separate results in a cleaner, safer, and more maintainable architecture.

## Current Status

Baseline release:

**v3.8.1-buch.1**

Based on the excellent IntelliCenter integration originally developed by the `joyfulhouse/intellicenter` project.

This repository maintains a stable, versioned branch customized for the Buch Home Assistant environment while preserving compatibility with future upstream improvements where appropriate.

## Credits

This project is based on the outstanding Pentair IntelliCenter integration originally developed and maintained by the **joyfulhouse/intellicenter** project.

Buch IntelliCenter is a privately maintained derivative that preserves upstream compatibility where practical while adding features and architectural enhancements to support the Buch Home Assistant ecosystem and the Pool Manager platform.
