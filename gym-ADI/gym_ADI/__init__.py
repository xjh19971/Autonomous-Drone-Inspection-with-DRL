import logging

from gym.envs.registration import register

logger = logging.getLogger(__name__)

register(
    id='ADI-v0',
    entry_point='gym_ADI.envs:ADIEnv'
)
