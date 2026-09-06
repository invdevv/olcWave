import yaml

from fastapi import HTTPException

from olcrtc.service import Containers
from database import async_session_factory
from profiles.db import ProfilesDB
from profiles.schemas import ProfileSchema

class Profiles:
    @staticmethod
    def validate(config: str):
        profile_obj: dict = yaml.safe_load(config)  

        profile_obj['mode'] = "srv"
        profile_obj.pop("data", None)

        profile_obj.pop('socks', None)
        
        profile_obj.pop("crypto", None)   

        return yaml.safe_dump(profile_obj, sort_keys=False)

    @staticmethod
    async def add(profile: ProfileSchema):
        profile.profile = Profiles.validate(profile.profile)

        if not profile.tag:
            raise HTTPException(status_code=400, detail="Tag cannot be empty")

        profile.tag = profile.tag.replace("-", "")

        async with async_session_factory() as db:  
            _= await ProfilesDB.add(db, profile) 

    @staticmethod
    async def get(tag: str):
        async with async_session_factory() as db:
            profile = await ProfilesDB.get(db, tag) 
        return profile

    @staticmethod
    async def update(tag: str, name: str, profile: str):
        profile = Profiles.validate(profile)

        async with async_session_factory() as db:
            _= await ProfilesDB.update(db, tag, name, profile)

        await Containers.stop_all_by_config_tag(tag)

    @staticmethod
    async def save_no_restart(tag: str, name: str, profile: str):
        """Persist a profile change WITHOUT stopping its containers.

        Used by the rotator to prune confirmed-dead tokens from a profile while
        the live srv keeps running (the tunnel must not drop for a config edit
        the user did not make).
        """
        profile = Profiles.validate(profile)

        async with async_session_factory() as db:
            _ = await ProfilesDB.update(db, tag, name, profile)

    @staticmethod
    async def delete(tag: str):
        async with async_session_factory() as db:  
            _=await ProfilesDB.delete(db, tag) 

        await Containers.remove_all_by_config_tag(tag)

    @staticmethod
    async def get_all() -> list[ProfileSchema]:
        async with async_session_factory() as db:  
            profiles: list[ProfileSchema] = await ProfilesDB.get_all(db) 
        
        return profiles