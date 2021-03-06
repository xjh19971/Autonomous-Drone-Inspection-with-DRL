import glob
import os
import random
import subprocess

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from gym import Env
from gym.spaces import Box


class ADIEnv(Env):
    def __init__(self, seed=0, rank=0, radius=None, z_0=0.35, obs_size=None, max_step=5, eval=False, simple=False):
        super().__init__()
        if radius is None:
            radius = [0.8, -1.0]  # r_min, r_max
        self.image_size = [480, 640]  # H, W
        if obs_size is None:
            self.obs_size = self.image_size
        elif type(obs_size) is int:
            self.obs_size = [obs_size, obs_size]
        else:
            self.obs_size = obs_size

        random.seed(seed)
        np.random.seed(seed)

        self.simple = simple
        self.radius = radius
        self.rank = rank
        if self.radius[1] == -1.0 or simple:
            self.enable_radius_change = False  # Sphere
            self.radius[1] = self.radius[0]
        else:
            self.enable_radius_change = True

        if self.simple:
            self.action_space = Box(low=-1, high=1, shape=[1], dtype=np.float32)
        elif not self.enable_radius_change:
            self.action_space = Box(low=-np.pi / 2, high=np.pi / 2, shape=[2], dtype=np.float32)
        else:
            self.action_space = Box(low=-np.pi / 2, high=np.pi / 2, shape=[3], dtype=np.float32)

        self.observation_space = Box(low=0, high=255,
                                     shape=[self.obs_size[0], self.obs_size[1], 3],
                                     dtype=np.uint8)

        self.savepath = '/media/data/dataset/ADI/NERF2'
        self.filename = '/media/data/dataset/ADI/image.png'
        self.ros_pattern = "rosservice call /call_robot \"{{x: {x:.1f}, y: {y:.1f}, z: {z:.1f}, yaw: {yaw:.1f},filename: {filename:s}, topic: '/hires/image_raw/compressed', robot: 'dragonfly12'}}\""
        self.max_retry_time = 100
        self.max_step = max_step
        self.z_0 = z_0
        self.center_image = self.image_size[0] // 2, self.image_size[1] // 2  # Y, X
        self.current_step = 0
        self.current_polar_position = self.radius[1], np.pi, np.pi / 2  # r, phi, theta
        self.current_score = 0
        self.action_safe = True

    def step(self, action):
        obs, detect, bump_done = self.get_image_detect_after_action(action)

        score1, score2, score3, score4 = self.get_score(detect)
        reward = score1 + score2 + score3 + score4  # reward = diff or score
        self.current_score = reward

        self.current_step += 1
        if self.current_step < self.max_step:
            if bump_done is True:
                done = True
            else:
                done = False
        else:
            done = True
        info = {'reward': reward, 'score': [score1, score2, score3, score4], 'polar': self.current_polar_position,
                'safe': self.action_safe}
        print(info)

        return obs, reward, done, info

    def render(self, mode='machine'):
        image = Image.open(self.filename)
        image_np = np.array(image)
        if mode == 'human':
            plt.imshow(image_np)
        return image_np

    def reset(self):

        # init
        # self.current_polar_position = self.radius[1], random.random()*np.pi*2, random.random()*np.pi/4 + np.pi/4  # r, phi, theta
        self.current_score = 0

        obs, detect, done = self.get_image_detect_after_action()
        score1, score2, score3, score4 = self.get_score(detect)
        self.current_score = score1 + score2 + score3 + score4
        self.current_step = 0

        return obs

    def get_image_detect_after_action(self, action=None):
        current_retry = 0
        image = None
        detect = None  # xmin ymin xmax ymax probability(detector) xmin ymin xmax ymax(vicon)
        self.action_safe = True
        done = False

        while image is None:
            if action is not None:
                self.current_polar_position = self.get_new_position(
                    action)  # action is delta r, delta phi and delta theta
            else:
                # reset, first goto 0,0,2, then random again
                while True:
                    try:
                        output_raw = None
                        process = subprocess.run(
                            self.ros_pattern.format(x=0.0, y=0.0, z=1.2, yaw=0.0, filename=self.filename), shell=True,
                            capture_output=True, timeout=10)
                        output_raw = process.stdout.decode("utf-8")
                        output = output_raw.split()
                        success = output[1][1:]  # raw string is "True
                        if success == "True":
                            break
                        else:
                            raise KeyError(process.stdout)
                    except Exception:
                        if output_raw is not None:
                            print(f'Error resetting: {output_raw}')
                        else:
                            print(f'Errpr resetting: Time out')
                if self.simple:
                    self.current_polar_position = self.radius[
                                                      1], random.random() * np.pi * 2, np.pi / 2  # r, phi, theta
                else:
                    self.current_polar_position = self.radius[
                                                      1], random.random() * np.pi * 2, random.random() * np.pi / 4 + np.pi / 4  # r, phi, theta
            x, y, z, yaw = self.polar_to_cart(self.current_polar_position)
            while current_retry < self.max_retry_time:
                try:
                    output_raw = None
                    process = subprocess.run(
                        self.ros_pattern.format(x=x, y=y, z=z, yaw=yaw, filename=self.filename), shell=True,
                        capture_output=True, timeout=10)
                    output_raw = process.stdout.decode("utf-8")
                    output = output_raw.split()
                    success = output[1][1:]  # raw string is "True
                    if success == "True" and int(output[7]) != -1:
                        image = Image.open(self.filename)
                        detect = output[2:-1]
                        break
                    elif success == 'Bump':
                        image = Image.open(self.filename)
                        detect = output[2:-1]
                        self.action_safe = False
                        if action is not None:
                            done = True  # done if not resetting
                        break
                    else:
                        raise KeyError(process.stdout)
                except Exception:
                    if output_raw is not None:
                        print(f'Error: {output_raw}')
                    else:
                        print(f'Error: Timeout')
                    current_retry += 1
            if image is None:
                current_retry = 0
                print(f'Sleep 10s: Cannot get the image after {self.max_retry_time} retries.')

        # save and resize image
        maxindex = 0
        for savefilename in glob.glob(self.savepath + '/*.png'):
            index = int(os.path.splitext(os.path.basename(savefilename))[0])
            if index > maxindex:
                maxindex = index
        maxindex = maxindex + 1
        image.save(self.savepath + f'/{maxindex}.png')
        image = image.resize(tuple(self.obs_size))
        with open(self.savepath + f'/{maxindex}.txt', 'w+') as f:
            f.write(f'{x} {y} {z} {yaw}')

        return np.array(image), detect, done

    def polar_to_cart(self, polar_position):
        r, phi, theta = polar_position
        x = r * np.sin(theta) * np.cos(phi)
        y = r * np.sin(theta) * np.sin(phi)
        z = r * np.cos(theta) + self.z_0
        yaw = phi - np.pi
        if yaw < 0:
            yaw += 2 * np.pi
        elif yaw >= 2 * np.pi:
            yaw -= 2 * np.pi

        return x, y, z, yaw

    def get_new_position(self, action):
        if self.simple:
            r_0, phi_0, theta_0 = self.current_polar_position
            d_phi = action[0] * np.pi / 2
            d_theta = 0
            d_r = 0
            r_t = r_0
            theta_t = theta_0
        elif not self.enable_radius_change:
            r_0, phi_0, theta_0 = self.current_polar_position
            d_phi, d_theta = action
            d_r = 0
            r_t = r_0
            theta_t = theta_0 + d_theta
        else:
            r_0, phi_0, theta_0 = self.current_polar_position
            d_r, d_phi, d_theta = action
            # normalize d_theta from [-pi/2, pi/2] to [-pi/4, pi/4]
            d_theta = (d_theta + np.pi / 2) / 2 - np.pi / 4
            # normalize d_r from [-pi/2, pi/2] to range
            d_r = (d_r / (np.pi / 2)) * (self.radius[1] - self.radius[0])
            r_t = r_0 + d_r
            theta_t = theta_0 + d_theta

        phi_t = phi_0 + d_phi

        # Return legal r, phi and theta
        if self.enable_radius_change:
            r_t = np.clip(r_t, self.radius[0], self.radius[1])
        if phi_t < 0:
            phi_t += 2 * np.pi
        elif phi_t > 2 * np.pi:
            phi_t -= 2 * np.pi

        if not self.simple:
            if theta_t < np.pi / 4:
                print('Touch top')
            elif theta_t > np.pi / 2:
                print('Touch bottom')
            theta_t = np.clip(theta_t, np.pi / 4, np.pi / 2)  # 45 degrees

        print(f'action:{action}')
        print(f'delta:{d_r}, {d_phi}, {d_theta}')
        print(f'final:{r_t}, {phi_t}, {theta_t}')

        return r_t, phi_t, theta_t

    def get_score(self, detect):

        print(detect)

        if self.action_safe is False:
            return 0, 0, 0, 0

        xmin, ymin, xmax, ymax, prob, xmin_gt, ymin_gt, xmax_gt, ymax_gt = detect  # 640, 480
        xmin, ymin, xmax, ymax, xmin_gt, ymin_gt, xmax_gt, ymax_gt = int(xmin), int(ymin), int(xmax), int(ymax), int(
            xmin_gt), int(ymin_gt), int(xmax_gt), int(ymax_gt)
        prob = float(prob)

        score1 = 1
        score2 = 0
        score3 = 0
        score4 = 0

        if prob >= 0.4:
            score2 = prob

            # The second part is iou of pred and gt if we get a bbox
            pred_area = (xmax - xmin) * (ymax - ymin)
            gt_area = (xmax_gt - xmin_gt) * (ymax_gt - ymin_gt)

            left = max(xmin, xmin_gt)
            right = min(xmax, xmax_gt)
            top = max(ymin, ymin_gt)
            bottom = min(ymax, ymax_gt)

            if left < right and top < bottom:
                intersection = (right - left) * (bottom - top)
            else:
                intersection = 0
            iou = intersection / (pred_area + gt_area - intersection + 1e-8)
            score3 = iou

            if iou > 0.4:
                # More score if the center of the bbox is located at the center of the image (currently use gt bbox)
                center_gt = (xmax_gt + xmin_gt) / 2, (ymax_gt + ymin_gt) / 2
                distance = np.sqrt(
                    (center_gt[0] - self.center_image[1]) ** 2 + (center_gt[1] - self.center_image[0]) ** 2)
                lower_bound = min(self.center_image) / 4
                upper_bound = min(self.center_image) / 2
                if distance <= lower_bound:
                    score4 = 2
                elif distance <= 2 * upper_bound:
                    score4 = 2 - (distance - lower_bound) / (upper_bound - lower_bound)

        return score1, score2, score3, score4
