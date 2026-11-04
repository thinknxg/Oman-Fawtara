# Copyright (c) 2026, thinkNXG and contributors

from oman_fawtara.vat.registers import get_register


def execute(filters=None):
	return get_register(filters, "sales")
