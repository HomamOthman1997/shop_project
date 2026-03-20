from typing import Optional


class ProviderFactory:
    _instances: dict[str, object] = {}

    @classmethod
    def get(cls, name: str) -> Optional[object]:
        name = name.lower()

        if name not in cls._instances:
            if name == "smspool":
                from .providers.smspool_provider import SMSPoolProvider

                cls._instances[name] = SMSPoolProvider()
            elif name == "telabot":
                from .providers.telabot_provider import TelabotProvider

                cls._instances[name] = TelabotProvider()
            elif name == "textverified":
                from .providers.textverified_provider import TextVerifiedProvider

                cls._instances[name] = TextVerifiedProvider()
            elif name == "herosms":
                from .providers.herosms_provider import HeroSMSProvider

                cls._instances[name] = HeroSMSProvider()
            elif name == "smsman":
                from .providers.smsman_provider import SMSManProvider

                cls._instances[name] = SMSManProvider()
            else:
                raise ValueError(f"Unknown provider '{name}'")

        return cls._instances[name]
