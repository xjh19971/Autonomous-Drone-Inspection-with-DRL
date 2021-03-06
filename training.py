import argparse
import os

import gym
import numpy as np
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.noise import NormalActionNoise
from stable_baselines3.common.utils import set_random_seed
from stable_baselines3.sac import SAC

from callback_buffer import CheckpointBufferCallback


# Reference: https://stable-baselines3.readthedocs.io/en/master/guide/examples.html#multiprocessing-unleashing-the-power-of-vectorized-environments

def make_env(env_id, rank, seed, radius, z_0, max_step, obs_size, eval, simple):
    """
    Utility function for multiprocessed env.
    :param z_0: z_0
    :param radius: [r_min, r_max]
    :param env_id: (str) the environment ID
    :param seed: (int) the inital seed for RNG
    :param rank: (int) index of the subprocess
    """

    def _init():
        env = gym.make(env_id, seed=seed, rank=rank, radius=radius, z_0=z_0, max_step=max_step, obs_size=obs_size,
                       eval=eval, simple=simple)
        env.seed(seed + rank)
        return env

    set_random_seed(seed)
    return _init


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    # data params
    parser.add_argument('-env_id', type=str, default='ADI-v0', choices='ADI-v0')
    parser.add_argument('-policy', type=str, default='cnn', choices='cnn')
    parser.add_argument('-global_seed', type=int, default=1)
    parser.add_argument('-max_envs_num', type=int, default=1)
    parser.add_argument('-batch_size', type=int, default=64)
    parser.add_argument('-r_max', type=float, default=-1.0)  # -1.0 means we only allow run on a sphere
    parser.add_argument('-r_min', type=float, default=0.8)
    parser.add_argument('-z_0', type=float, default=0.35)
    parser.add_argument('-max_step', type=int, default=3)
    parser.add_argument('-obs_size', type=int, default=256)
    parser.add_argument('-buffer_size', type=int, default=10000)
    parser.add_argument('-total_timesteps', type=int, default=10000)
    parser.add_argument('-simple', action='store_true')

    opt = parser.parse_args()
    opt.eval = False
    opt.radius = [opt.r_min, opt.r_max]

    # Multiple env
    # env = SubprocVecEnv(
    #     [make_env(opt.env_id, i, opt.global_seed, opt.radius, opt.z_0, opt.max_step, opt.obs_size) for i in range(opt.max_envs_num)])
    # Single env
    env = make_env(opt.env_id, 0, opt.global_seed, opt.radius, opt.z_0, opt.max_step, opt.obs_size, opt.eval,
                   opt.simple)()

    if opt.policy == 'cnn':
        policy_name = 'CnnPolicy'
    else:
        raise KeyError

    # Check env
    check_env(env)

    checkpoint_callback = CheckpointBufferCallback(save_freq=100, save_path='./logs/', name_prefix='checkpoint')

    n_actions = env.action_space.shape

    action_noise = NormalActionNoise(mean=np.zeros(n_actions), sigma=0.1 * np.ones(n_actions))

    if os.path.isfile('./final_model_6b.zip'):
        print('Load model')
        model = SAC.load('./final_model_6b', tensorboard_log="./tb/", env=env)
        print(f'Current steps: {model.num_timesteps}')
    else:
        model = SAC(policy_name, env, verbose=1, buffer_size=opt.buffer_size, batch_size=opt.batch_size, train_freq=1,
                    gradient_steps=3, tensorboard_log="./tb/", ent_coef='auto_0.7', action_noise=action_noise)
        print('Create new model')

    if os.path.isfile('./buffer_init.pkl'):
        print('Load Buffer')
        model.load_replay_buffer('./buffer_init')

    try:
        print('start learning')
        model._last_obs = None
        model.learn(total_timesteps=opt.total_timesteps, callback=checkpoint_callback, tb_log_name="simple",
                    log_interval=3, reset_num_timesteps=False)
    finally:
        model.save('./final_model_inter')
        model.save_replay_buffer('./buffer_inter')
