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
            elif name == "nonvoip":
                from .providers.nonvoip_provider import NonVoipProvider

                cls._instances[name] = NonVoipProvider()
            elif name == "pvadeals":
                from .providers.pvadeals_provider import PVADealsProvider

                cls._instances[name] = PVADealsProvider()
            elif name == "smsready":
                from .providers.smsready_provider import SMSReadyProvider

                cls._instances[name] = SMSReadyProvider()
            elif name == "pvapins":
                from .providers.pvapins_provider import PVAPinsProvider

                cls._instances[name] = PVAPinsProvider()
            else:
                raise ValueError(f"Unknown provider '{name}'")

        return cls._instances[name]
