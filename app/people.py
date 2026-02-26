import random

_FIRST_NAMES = [
    "Ana", "Bruno", "Carla", "Diego", "Elena", "Felipe", "Gabriela",
    "Hugo", "Isabela", "João", "Karen", "Lucas", "Marina", "Nathan",
    "Olivia", "Pedro", "Rafael", "Sofia", "Tiago", "Vitória",
]
_LAST_NAMES = [
    "Almeida", "Araújo", "Barbosa", "Carvalho", "Costa", "Ferreira",
    "Freitas", "Gomes", "Lima", "Martins", "Nascimento", "Oliveira",
    "Pereira", "Ribeiro", "Rocha", "Rodrigues", "Santos", "Silva",
    "Souza", "Tavares",
]
_EMAIL_DOMAINS = [
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com.br", "icloud.com",
]
_DDDS = ["11", "21", "31", "41", "51", "61", "71", "81", "85", "91"]


def _cpf_digit(digits: list[int], factor: int) -> int:
    total = sum(f * d for f, d in zip(range(factor, 1, -1), digits))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def generate_cpf() -> str:
    base = [random.randint(0, 9) for _ in range(9)]
    d1 = _cpf_digit(base, 10)
    d2 = _cpf_digit(base + [d1], 11)
    digits = base + [d1, d2]
    return "{}{}{}.{}{}{}.{}{}{}-{}{}".format(*digits)


def generate_phone() -> str:
    ddd    = random.choice(_DDDS)
    number = "9" + "".join(str(random.randint(0, 9)) for _ in range(8))
    return f"+55{ddd}{number}"


def random_payer() -> dict:
    first = random.choice(_FIRST_NAMES)
    last  = random.choice(_LAST_NAMES)
    seq   = random.randint(1, 999)

    return {
        "amount": random.randint(1_000, 50_000),
        "name":   f"{first} {last}",
        "tax_id": generate_cpf(),
        "email":  f"{first.lower()}.{last.lower()}{seq}@{random.choice(_EMAIL_DOMAINS)}",
        "phone":  generate_phone(),
    }
