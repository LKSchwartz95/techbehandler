"""Remediation plugins package.

Each module in this package can define a `TAG_TO_REMEDIATION` dictionary
mapping LLM-generated tags to remediation suggestion strings. The
`remediation_engine` automatically loads these mappings at runtime.
"""
