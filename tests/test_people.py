import re
from app.people import _cpf_digit, generate_cpf, generate_phone, random_payer


class TestCpfDigit:
    def test_returns_zero_when_remainder_less_than_2(self):
        assert _cpf_digit([0] * 9, 10) == 0

    def test_returns_eleven_minus_remainder_otherwise(self):
        result = _cpf_digit([1] * 9, 10)
        assert result == 11 - (sum(f * 1 for f in range(10, 1, -1)) % 11)


class TestGenerateCpf:
    CPF_RE = re.compile(r"^\d{3}\.\d{3}\.\d{3}-\d{2}$")


    def test_format(self):
        assert self.CPF_RE.match(generate_cpf())


    def test_uniqueness(self):
        assert len({generate_cpf() for _ in range(30)}) > 15


    def test_check_digits_valid(self):
        for _ in range(20):
            cpf = generate_cpf().replace(".", "").replace("-", "")
            digits = [int(c) for c in cpf]
            total = sum((10 - i) * d for i, d in enumerate(digits[:9]))
            r = total % 11
            assert digits[9] == (0 if r < 2 else 11 - r)
            total = sum((11 - i) * d for i, d in enumerate(digits[:10]))
            r = total % 11
            assert digits[10] == (0 if r < 2 else 11 - r)


class TestGeneratePhone:
    def test_starts_with_country_code(self):
        assert generate_phone().startswith("+55")


    def test_length(self):
        assert len(generate_phone()) == 14


    def test_mobile_prefix(self):
        assert generate_phone()[5] == "9"


class TestRandomPayer:
    def test_has_required_keys(self):
        assert {"amount", "name", "tax_id", "email", "phone"}.issubset(random_payer())


    def test_amount_in_range(self):
        for _ in range(100):
            assert 1_000 <= random_payer()["amount"] <= 50_000


    def test_email_contains_at(self):
        assert "@" in random_payer()["email"]


    def test_name_has_two_parts(self):
        assert len(random_payer()["name"].split()) >= 2
