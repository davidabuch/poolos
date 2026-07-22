# Buch IntelliCenter Architecture

## Mission

Buch IntelliCenter is the hardware integration layer between Pentair IntelliCenter equipment and Home Assistant.

Its purpose is to provide a reliable, maintainable, and versioned interface to Pentair pool equipment while remaining independent of higher-level automation logic.

---

# Responsibilities

Buch IntelliCenter is responsible for:

- Communication with Pentair IntelliCenter
- Equipment discovery
- Device state synchronization
- Entity creation
- Command execution
- Diagnostics
- Hardware abstraction
- Compatibility with Home Assistant

Buch IntelliCenter is **not** responsible for automation decisions.

---

# Pool Manager

Pool Manager is a separate project.

Pool Manager consumes information provided by Buch IntelliCenter and makes operational decisions.

Examples include:

- Scheduling
- Runtime optimization
- Solar optimization
- Safety policies
- Equipment ownership
- Lighting synchronization
- Water chemistry automation
- Notifications

---

# Design Principle

Buch IntelliCenter answers:

> "What is the equipment doing?"

Pool Manager answers:

> "What should the equipment do?"

These responsibilities should never overlap.

---

# Architectural Principles

Every feature added to Buch IntelliCenter should satisfy the following principles:

1. **Single Responsibility**
   - The integration should focus on communicating with Pentair equipment and exposing that functionality to Home Assistant.

2. **Hardware First**
   - Features belong here only if they directly represent or control physical equipment.

3. **Stable Interface**
   - Changes should preserve compatibility whenever practical so that higher-level software can rely on a predictable interface.

4. **Extensibility**
   - New capabilities should be added through clean extension points rather than tightly coupling unrelated features.

5. **Observability**
   - Equipment state should be easy to inspect, diagnose, and troubleshoot.

6. **Safety**
   - Hardware control should always favor predictable, deterministic behavior over convenience.

---

# Long-Term Goal

Buch IntelliCenter should expose a stable interface that higher-level software can depend upon without requiring knowledge of internal Pentair implementation details.

This allows Pool Manager and future automation platforms to evolve independently while maintaining compatibility with the underlying equipment.
