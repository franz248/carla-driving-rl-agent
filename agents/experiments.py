"""A collection of various experiment settings."""

import cv2
import math
import carla
import pygame
import numpy as np

from typing import Optional, ClassVar
from tensorforce import Agent

from agents import Agents, SensorSpecs, Specs
from agents.environment import SynchronousCARLAEnvironment
from agents import env_utils
from tools import utils


# -------------------------------------------------------------------------------------------------
# -- Baseline Experiments
# -------------------------------------------------------------------------------------------------

class BaselineExperiment(SynchronousCARLAEnvironment):
    ACTIONS_SPEC = dict(type='float', shape=(3,), min_value=-1.0, max_value=1.0)
    DEFAULT_ACTIONS = np.array([0., 0., 0.])

    # vehicle: speed, accelerometer (x, y, z), gyroscope (x, y, z), position (x, y), destination (x, y), compass
    VEHICLE_FEATURES_SPEC = dict(type='float', shape=(12,))

    def default_sensors(self) -> dict:
        return dict(imu=SensorSpecs.imu(),
                    collision=SensorSpecs.collision_detector(),
                    camera=SensorSpecs.rgb_camera(position='front',
                                                  attachment_type='Rigid',
                                                  image_size_x=self.window_size[0], image_size_y=self.window_size[1],
                                                  sensor_tick=1.0 / self.fps))

    def default_agent(self, **kwargs) -> Agent:
        return Agents.baseline(self, **kwargs)

    def reward(self, actions, time_cost=-1.0, b=-1000.0, c=2.0, d=2.0):
        # Direction term: alignment of the vehicle's heading direction with the waypoint's forward vector
        closest_waypoint = self.route.next.waypoint
        similarity = utils.cosine_similarity(self.vehicle.get_transform().get_forward_vector(),  # heading direction
                                             closest_waypoint.transform.get_forward_vector())
        speed = utils.speed(self.vehicle)

        if similarity > 0:
            direction_penalty = (speed + 1) * similarity  # speed + 1, to avoid 0 speed
        else:
            direction_penalty = (speed + 1) * similarity * d

        if self.travelled_distance <= self.route.size:
            efficiency_term = 0.0
        else:
            efficiency_term = -(self.travelled_distance - self.route.size) - self.route.distance_to_destination()

            # travelled more than route size, zero direction_penalty if positive
            if direction_penalty > 0.0:
                direction_penalty = 0.0

        # Speed-limit compliance:
        speed_limit = self.vehicle.get_speed_limit()

        if speed <= speed_limit:
            speed_penalty = 0.0 if speed > 10.0 else -1.0
        else:
            speed_penalty = c * (speed_limit - speed)

        return time_cost - self.collision_penalty + efficiency_term + direction_penalty + speed_penalty

    def _get_vehicle_features(self):
        t = self.vehicle.get_transform()

        imu_sensor = self.sensors['imu']
        gyroscope = imu_sensor.gyroscope
        accelerometer = imu_sensor.accelerometer

        return [min(utils.speed(self.vehicle), 150.0),
                # Accelerometer:
                accelerometer[0],
                accelerometer[1],
                accelerometer[2],
                # Gyroscope:
                gyroscope[0],
                gyroscope[1],
                gyroscope[2],
                # Location
                t.location.x,
                t.location.y,
                # Destination:
                self.destination.x,
                self.destination.y,
                # Compass:
                math.radians(imu_sensor.compass)]

    def actions_to_control(self, actions):
        # Throttle
        if actions[0] < 0:
            self.control.throttle = 0.0
            self.control.brake = 1.0
        else:
            self.control.throttle = 1.0
            self.control.brake = 0.0

        # if actions[0] < -0.33:
        #     self.control.throttle = 0.3
        # elif actions[0] > 0.33:
        #     self.control.throttle = 0.9
        # else:
        #     self.control.throttle = 0.5

        # Steer
        if actions[1] < -0.33:
            self.control.steer = -0.5
        elif actions[1] > 0.33:
            self.control.steer = 0.5
        else:
            self.control.steer = 0

        # self.control.reverse = bool(actions[2] < 0)
        self.control.brake = 0.0 if actions[2] < 0 else float(actions[2])


# -------------------------------------------------------------------------------------------------
# -- Experiments
# -------------------------------------------------------------------------------------------------

class RouteFollowExperiment(SynchronousCARLAEnvironment):
    """Base class (with basic behaviour) for CARLA Experiments"""

    # skill, throttle/brake intensity, steer
    ACTIONS_SPEC = dict(type='float', shape=(3,), min_value=-1.0, max_value=1.0)
    DEFAULT_ACTIONS = np.array([0.0, 0.0, 0.0])

    # A "skill" is a high-level action
    SKILLS = {0: 'idle', 1: 'brake',
              2: 'forward', 3: 'forward left', 4: 'forward right',
              5: 'backward', 6: 'backward left', 7: 'backward right'}

    # speed, vehicle control (4), accelerometer (3), gyroscope (3), target waypoint's features (5), compass
    VEHICLE_FEATURES_SPEC = dict(type='float', shape=(17,))

    def default_sensors(self) -> dict:
        sensors = super().default_sensors()
        SensorSpecs.set(sensors['camera'], position='on-top2', attachment_type='Rigid')
        return sensors

    def default_agent(self, max_episode_timesteps: int, batch_size=256) -> Agent:
        policy_spec = dict(network=Specs.network_v2(conv=dict(activation='leaky-relu'),
                                                    final=dict(layers=2, units=256)),
                           distributions='gaussian')

        critic_spec = policy_spec.copy()
        critic_spec['temperature'] = 0.5
        critic_spec['optimizer'] = dict(type='synchronization', sync_frequency=1, update_weight=1.0)

        return Agents.ppo_like(self, max_episode_timesteps, policy=policy_spec, critic=critic_spec,
                               batch_size=batch_size,
                               preprocessing=Specs.my_preprocessing(image_shape=(75, 105, 1), stack_images=10),
                               summarizer=Specs.summarizer(frequency=batch_size))

    def terminal_condition(self, distance_threshold=2.0):
        super().terminal_condition(distance_threshold=distance_threshold)

    def get_skill_name(self):
        skill = env_utils.scale(self.prev_actions[0])
        return self.SKILLS[int(skill)]

    def actions_to_control(self, actions):
        skill = self.get_skill_name()
        reverse = self.control.reverse

        if skill == 'brake':
            throttle = 0.0
            brake = max(0.1, (actions[1] + 1) / 2.0)
            steer = float(actions[2])
        elif skill == 'forward':
            throttle = max(0.1, (actions[1] + 1) / 2.0)
            brake = 0.0
            steer = 0.0
            reverse = False
        elif skill == 'forward right':
            throttle = max(0.1, (actions[1] + 1) / 2.0)
            brake = 0.0
            steer = max(0.1, abs(actions[2]))
            reverse = False
        elif skill == 'forward left':
            throttle = max(0.1, (actions[1] + 1) / 2.0)
            brake = 0.0
            steer = min(-0.1, -abs(actions[2]))
            reverse = False
        elif skill == 'backward':
            throttle = max(0.1, (actions[1] + 1) / 2.0)
            brake = 0.0
            steer = 0.0
            reverse = True
        elif skill == 'backward left':
            throttle = max(0.1, (actions[1] + 1) / 2.0)
            brake = 0.0
            steer = max(0.1, abs(actions[2]))
            reverse = True
        elif skill == 'backward right':
            throttle = max(0.1, (actions[1] + 1) / 2.0)
            brake = 0.0
            steer = min(-0.1, -abs(actions[2]))
            reverse = True
        else:
            # idle/stop
            throttle = 0.0
            brake = 0.0
            steer = 0.0
            reverse = False

        self.control.throttle = float(throttle)
        self.control.brake = float(brake)
        self.control.steer = float(steer)
        self.control.reverse = reverse
        self.control.hand_brake = False

    def _get_vehicle_features(self):
        control = self.vehicle.get_control()
        imu_sensor = self.sensors['imu']
        gyroscope = imu_sensor.gyroscope
        accelerometer = imu_sensor.accelerometer

        # TODO: substitute accelerometer with vehicle.get_acceleration()? (3D vector)
        # TODO: consider adding 'vehicle.get_angular_velocity()' (3D vector)
        # TODO: substitute speed with 'vehicle.get_velocity()'? (3D vector)
        # TODO: add vehicle's light state

        return [math.log2(1.0 + utils.speed(self.vehicle)),  # speed
                # Vehicle control:
                control.throttle,
                control.steer,
                control.brake,
                float(control.reverse),
                # Accelerometer:
                accelerometer[0],
                accelerometer[1],
                accelerometer[2],
                # Gyroscope:
                gyroscope[0],
                gyroscope[1],
                gyroscope[2],
                # Target (next) waypoint's features:
                self.similarity,
                self.forward_vector.x,
                self.forward_vector.y,
                self.forward_vector.z,
                self.route.distance_to_next_waypoint(),
                # Compass:
                math.radians(imu_sensor.compass)]

    def debug_text(self, actions):
        speed_limit = self.vehicle.get_speed_limit()
        speed = utils.speed(self.vehicle)

        if speed > speed_limit:
            speed_text = dict(text='Speed %.1f km/h' % speed, color=(255, 0, 0))
        else:
            speed_text = 'Speed %.1f km/h' % speed

        return ['%d FPS' % self.clock.get_fps(),
                '',
                'Throttle: %.2f' % self.control.throttle,
                'Steer: %.2f' % self.control.steer,
                'Brake: %.2f' % self.control.brake,
                'Reverse: %s' % ('T' if self.control.reverse else 'F'),
                'Hand brake: %s' % ('T' if self.control.hand_brake else 'F'),
                '',
                speed_text,
                'Speed limit %.1f km/h' % speed_limit,
                '',
                'Similarity %.2f' % self.similarity,
                'Waypoint\'s Distance %.2f' % self.route.distance_to_next_waypoint(),
                '',
                'Reward: %.2f' % self.reward(actions),
                'Collision penalty: %.2f' % self.collision_penalty,
                'Skill: %s' % self.get_skill_name()]


class ActionPenaltyExperiment(RouteFollowExperiment):
    # skill, throttle or brake, steer, reverse
    ACTIONS_SPEC = dict(type='float', shape=(4,), min_value=-1.0, max_value=1.0)
    DEFAULT_ACTIONS = np.array([0.0, 0.0, 0.0, 0.0])

    # TODO: consider to 'decay' actions sa training goes on
    def actions_to_control(self, actions):
        self.control.throttle = float(actions[1]) if actions[1] > 0 else 0.0
        self.control.brake = float(-actions[1]) if actions[1] < 0 else 0.0
        self.control.steer = float(actions[2])
        self.control.reverse = bool(actions[3] > 0)

    def action_penalty(self):
        pass


class RadarSegmentationExperiment(RouteFollowExperiment):
    """Equips the vehicle with RADAR and semantic segmentation camera"""

    def default_sensors(self) -> dict:
        sensors = super().default_sensors()
        sensors['camera'] = SensorSpecs.segmentation_camera(position='on-top2',
                                                            attachment_type='Rigid',
                                                            image_size_x=self.image_size[0],
                                                            image_size_y=self.image_size[1],
                                                            sensor_tick=self.tick_time)
        # sensors['depth'] = SensorSpecs.depth_camera(position='on-top2',
        #                                             attachment_type='Rigid',
        #                                             image_size_x=self.image_size[0],
        #                                             image_size_y=self.image_size[1],
        #                                             sensor_tick=self.tick_time)

        sensors['radar'] = SensorSpecs.radar(position='radar', sensor_tick=self.tick_time)
        return sensors

    def on_collision(self, event: carla.CollisionEvent, penalty=1000.0, max_impulse=400.0):
        actor_type = event.other_actor.type_id

        if 'pedestrian' in actor_type:
            self.collision_penalty += penalty
            self.should_terminate = True
        elif 'vehicle' in actor_type:
            self.collision_penalty += penalty / 2.0
            self.should_terminate = True
        else:
            self.collision_penalty += penalty / 10.0
            self.should_terminate = False

    # def on_sensors_data(self, data: dict) -> dict:
    #     data = super().on_sensors_data(data)
    #     data['depth'] = self.sensors['depth'].convert_image(data['depth'])
    #     depth = env_utils.cv2_grayscale(data['depth'], depth=3)
    #     # data['camera'] = cv2.multiply(data['camera'], cv2.log(1.0 * data['depth']))
    #
    #     data['camera'] = np.multiply(data['camera'], 255 - depth)
    #
    #     # data['camera'] = env_utils.cv2_grayscale(data['camera'], depth=3)
    #     return data

    def render(self, sensors_data: dict):
        super().render(sensors_data)
        print('points:', sensors_data['radar'].get_detection_count())
        env_utils.draw_radar_measurement(debug_helper=self.world.debug, data=sensors_data['radar'])


class CompleteStateExperiment(RouteFollowExperiment):
    """Equips sensors: semantic camera + depth camera + radar"""

    # Control: throttle or brake, steer, reverse
    CONTROL_SPEC = dict(type='float', shape=(3,), min_value=-1.0, max_value=1.0)
    DEFAULT_CONTROL = np.array([0.0, 0.0, 0.0], dtype=np.float32)

    # Skills: high-level actions
    SKILLS = {0: 'wait', 1: 'brake',
              2: 'steer right', 3: 'steer left',
              4: 'forward', 5: 'forward left', 6: 'forward right',
              7: 'backward', 8: 'backward left', 9: 'backward right'}
    DEFAULT_SKILL = np.array([0.0], dtype=np.float32)
    SKILL_SPEC = dict(type='float', shape=1, min_value=0.0, max_value=len(SKILLS) - 1.0)

    DEFAULT_ACTIONS = dict(control=DEFAULT_CONTROL, skill=DEFAULT_SKILL)

    def __init__(self, time_horizon=5, *args, **kwargs):
        assert isinstance(time_horizon, int)
        super().__init__(*args, **kwargs)

        self.time_horizon = time_horizon
        self.time_index = 0
        self.radar_index = 0
        self.image_shape = self.image_shape[:2] + (time_horizon,)  # consider grayscale images
        # self.radar_obs_per_step = math.floor(1500 / self.fps) + 1

        # TODO: try dtype=np.float16 to save memory
        # features' default values (add a temporal axis)
        # NOTE: features are 2D-arrays so that applying convolutions is more efficiently than recurrences
        self.DEFAULT_VEHICLE = np.zeros((time_horizon, self.VEHICLE_FEATURES_SPEC['shape'][0]), dtype=np.float32)
        self.DEFAULT_SKILLS = np.zeros((time_horizon,), dtype=np.float32)
        self.EMPTY_ACTIONS = np.zeros((time_horizon, self.DEFAULT_CONTROL.shape[0]), dtype=np.float32)
        self.DEFAULT_RADAR = np.zeros((50 * time_horizon, 4), dtype=np.float32)
        self.DEFAULT_IMAGE = np.zeros(self.image_shape, dtype=np.float32)
        self.DEFAULT_ROAD = np.zeros((time_horizon, self.ROAD_FEATURES_SPEC['shape'][0]), dtype=np.float32)

        # empty observations (to be filled on temporal axis)
        self.actions_obs = self.EMPTY_ACTIONS.copy()
        self.vehicle_obs = self.DEFAULT_VEHICLE.copy()
        self.skills_obs = self.DEFAULT_SKILLS.copy()
        self.radar_obs = self.DEFAULT_RADAR.copy()
        self.image_obs = self.DEFAULT_IMAGE.copy()
        self.road_obs = self.DEFAULT_ROAD.copy()

    def default_sensors(self) -> dict:
        sensors = super().default_sensors()
        sensors['camera'] = SensorSpecs.segmentation_camera(position='on-top2', attachment_type='Rigid',
                                                            image_size_x=self.image_size[0],
                                                            image_size_y=self.image_size[1],
                                                            sensor_tick=self.tick_time)
        sensors['radar'] = SensorSpecs.radar(position='radar', sensor_tick=self.tick_time)
        return sensors

    def states(self):
        # TODO: consider adding 'rewards' to state space!
        return dict(image=dict(shape=self.image_shape),
                    radar=dict(type='float', shape=self.DEFAULT_RADAR.shape),
                    road=dict(type='float', shape=self.DEFAULT_ROAD.shape),
                    vehicle=dict(type='float', shape=self.DEFAULT_VEHICLE.shape),
                    past_actions=dict(type='float', shape=self.EMPTY_ACTIONS.shape),
                    past_skills=dict(type='float', shape=self.DEFAULT_SKILLS.shape, min_value=0.0,
                                     max_value=len(self.SKILLS) - 1.0))

    def actions(self):
        return dict(control=self.CONTROL_SPEC,
                    skill=self.SKILL_SPEC)

    def execute(self, actions, record_path: str = None):
        state, terminal, reward = super().execute(actions, record_path=record_path)
        self.time_index = (self.time_index + 1) % self.time_horizon

        return state, terminal, reward

    def reward(self, actions, time_cost=-1.0, b=2.0, c=2.0, d=2.0, k=6.0):
        # normalize reward to [-k, +1] where 'k' is an arbitrary multiplier representing a big negative value
        v = max(utils.speed(self.vehicle), 1.0)
        r = super().reward(actions)
        r = max(r, -k * v)
        return (r / v) + self.action_penalty(actions)

    def reset(self, soft=False) -> dict:
        self.time_index = 0
        self.radar_index = 0

        # reset observations (np.copyto() should reuse memory...)
        np.copyto(self.actions_obs, self.EMPTY_ACTIONS)
        np.copyto(self.road_obs, self.DEFAULT_ROAD)
        np.copyto(self.radar_obs, self.DEFAULT_RADAR)
        np.copyto(self.image_obs, self.DEFAULT_IMAGE)
        np.copyto(self.skills_obs, self.DEFAULT_SKILLS)
        np.copyto(self.vehicle_obs, self.DEFAULT_VEHICLE)

        return super().reset(soft=soft)

    def actions_to_control(self, actions):
        """Specifies the mapping between an actions vector and the vehicle's control."""
        actions = actions['control']
        self.control.throttle = float(actions[0]) if actions[0] > 0 else 0.0
        self.control.brake = float(-actions[0]) if actions[0] < 0 else 0.0
        self.control.steer = float(actions[1])
        self.control.reverse = bool(actions[2] > 0)
        self.control.hand_brake = False

    def get_skill_name(self):
        """Returns skill's name"""
        index = round(self.prev_actions['skill'][0])
        return self.SKILLS[index]

    @staticmethod
    def action_penalty(actions, eps=0.05) -> float:
        """Returns the amount of coordination, defined as the number of actions that agree with the skill"""
        skill = round(actions['skill'][0])
        a0, steer, a2 = actions['control']
        num_actions = len(actions['control'])
        throttle = max(a0, 0.0)
        reverse = a2 > 0
        count = 0

        # wait/noop
        if skill == 0:
            count += 1 if throttle > eps else 0

        # brake
        elif skill == 1:
            count += 1 if throttle > eps else 0

        # steer right/left
        elif skill in [2, 3]:
            count += 1 if -eps <= steer <= eps else 0
            count += 1 if throttle > eps else 0

        # forward right/left
        elif skill in [4, 5, 6]:
            count += 1 if reverse else 0
            count += 1 if throttle < eps else 0

            if skill == 4:
                count += 0 if -eps <= steer <= eps else 1
            elif skill == 5:
                count += 1 if steer > -eps else 0
            else:
                count += 1 if steer < eps else 0

        # backward right/left
        elif skill in [7, 8, 9]:
            count += 1 if not reverse else 0
            count += 1 if throttle < eps else 0

            if skill == 7:
                count += 0 if -eps <= steer <= eps else 1
            elif skill == 8:
                count += 1 if steer > -eps else 0
            else:
                count += 1 if steer < eps else 0

        return num_actions - count

    # def render(self, sensors_data: dict):
    #     # depth = camera.convert(data)
    #     # depth = np.stack((depth,) * 3, axis=-1) / depth.max() * 255.0
    #     # print(depth.shape, depth.min(), depth.max())
    #
    #     # sensors_data['camera'] = np.mean(sensors_data['camera'], axis=-1)
    #     # sensors_data['camera'] = env_utils.to_grayscale(sensors_data['camera'])
    #     # sensors_data['camera'] = sensors_data['camera'][..., ::-1]
    #     super().render(sensors_data)

    def on_sensors_data(self, data: dict) -> dict:
        data = super().on_sensors_data(data)
        data['radar'] = self.sensors['radar'].convert(data['radar'])
        return data

    def debug_text(self, actions):
        text = super().debug_text(actions)
        text[-1] = 'Skill (%d) = %s' % (round(self.prev_actions['skill'][0]), self.get_skill_name())
        text.append('Coordination %d' % self.action_penalty(actions))

        return text

    def _get_observation(self, sensors_data: dict) -> dict:
        if len(sensors_data.keys()) == 0:
            # sensor_data is empty so, return a default observation
            return dict(image=self.DEFAULT_IMAGE, radar=self.DEFAULT_RADAR, vehicle=self.DEFAULT_VEHICLE,
                        road=self.DEFAULT_ROAD, past_actions=self.EMPTY_ACTIONS, past_skills=self.DEFAULT_SKILLS)

        # grayscale image, plus -1, +1 scaling
        image = (2 * env_utils.cv2_grayscale(sensors_data['camera']) - 255.0) / 255.0
        radar = sensors_data['radar']
        t = self.time_index

        # concat new observations along the temporal axis:
        self.vehicle_obs[t] = self._get_vehicle_features()
        self.actions_obs[t] = self.prev_actions['control'].copy()
        self.skills_obs[t] = self.prev_actions['skill'].copy()
        self.road_obs[t] = self._get_road_features()
        self.image_obs[:, :, t] = image

        # copy radar measurements
        for i, detection in enumerate(radar):
            index = (self.radar_index + i) % self.radar_obs.shape[0]
            self.radar_obs[index] = detection

        # observation
        return dict(image=self.image_obs, radar=self.radar_obs, vehicle=self.vehicle_obs,
                    road=self.road_obs, past_actions=self.actions_obs, past_skills=self.skills_obs)


# -------------------------------------------------------------------------------------------------
# -- Play Environments
# -------------------------------------------------------------------------------------------------

# TODO: override 'train' (if necessary) -> consider to add 'play' and 'record' methods instead of 'train'
class CARLAPlayEnvironment(RouteFollowExperiment):
    ACTIONS_SPEC = dict(type='float', shape=(5,), min_value=-1.0, max_value=1.0)
    DEFAULT_ACTIONS = [0.0, 0.0, 0.0, 0.0, 0.0]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print('Controls: (W, or UP) accelerate, (A or LEFT) steer left, (D or RIGHT) steer right, (S or DOWN) brake, '
              '(Q) toggle reverse, (SPACE) hand-brake, (ESC) quit.')

    def default_sensors(self) -> dict:
        sensors = super().default_sensors()
        sensors['camera']['transform'] = SensorSpecs.get_position('top')
        return sensors

    def default_agent(self, **kwargs) -> Agent:
        return Agents.keyboard(self)

    def play(self):
        """Let's you control the vehicle with a keyboard."""
        states = self.reset()
        agent = self.default_agent()
        terminal = False

        try:
            with self.synchronous_context:
                while not terminal:
                    actions = agent.act(states)
                    states, terminal, reward = self.execute(actions)
                    agent.observe(reward, terminal)
        finally:
            agent.close()
            self.close()

    def actions_to_control(self, actions):
        self.control.throttle = actions[0]
        self.control.steer = actions[1]
        self.control.brake = actions[2]
        self.control.reverse = bool(actions[3])
        self.control.hand_brake = bool(actions[4])

    def before_world_step(self):
        if self.should_debug:
            self.route.draw_route(self.world.debug, life_time=1.0 / self.fps)
            self.route.draw_next_waypoint(self.world.debug, self.vehicle.get_location(), life_time=1.0 / self.fps)


class PlayEnvironment2(RadarSegmentationExperiment, CARLAPlayEnvironment):

    def before_world_step(self):
        pass


class PlayEnvironment3(CompleteStateExperiment, CARLAPlayEnvironment):

    def before_world_step(self):
        pass


# -------------------------------------------------------------------------------------------------
# -- Pretraining Experiments
# -------------------------------------------------------------------------------------------------

# TODO: improve, solve the issue with env.reset()
class CARLAPretrainExperiment(CompleteStateExperiment):

    def default_agent(self, **kwargs) -> Agent:
        return Agents.pretraining(self, speed=30.0, **kwargs)

    def reward(self, actions, time_cost=-1.0, b=2.0, c=2.0, d=2.0, k=6.0):
        speed = utils.speed(self.vehicle)
        direction_penalty = speed + 1
        speed_limit = self.vehicle.get_speed_limit()

        if speed <= speed_limit:
            speed_penalty = 0.0 if speed > 10.0 else -1.0
        else:
            speed_penalty = c * (speed_limit - speed)

        r = time_cost - self.collision_penalty + direction_penalty + speed_penalty

        # normalize
        v = max(speed, 1.0)
        r = max(r, -k * v)
        return (r / v) + self.action_penalty(actions)

    @staticmethod
    def action_penalty(actions, eps=0.05) -> float:
        ap = CompleteStateExperiment.action_penalty(actions)
        assert ap == len(actions['control'])
        return ap

    def _skill_from_control(self, control: carla.VehicleControl, eps=0.05) -> (float, str):
        t = control.throttle
        s = control.steer
        b = control.brake
        r = control.reverse

        # backward:
        if r and (t > eps) and (b <= eps):
            if s > eps:
                skill = 9
            elif s < -eps:
                skill = 8
            else:
                skill = 7
        # forward:
        elif (not r) and (t > eps) and (b <= eps):
            if s > eps:
                skill = 6
            elif s < -eps:
                skill = 5
            else:
                skill = 4
        # steer:
        elif (t <= eps) and (b <= eps):
            if s > eps:
                skill = 2
            elif s < -eps:
                skill = 3
            else:
                skill = 0
        # brake:
        elif b > eps:
            skill = 1
        else:
            skill = 0

        return skill, self.SKILLS[skill]

    def control_to_actions(self, control: carla.VehicleControl):
        skill, name = self._skill_from_control(control)
        skill = np.array([skill], dtype=np.float32)
        steer = control.steer
        reverse = bool(control.reverse > 0)

        if control.throttle > 0.0:
            return dict(control=[control.throttle, steer, reverse], skill=skill), name
        else:
            return dict(control=[-control.brake, steer, reverse], skill=skill), name

    def debug_text(self, actions):
        text = super().debug_text(actions)
        return text[:11] + text[14:]

# -------------------------------------------------------------------------------------------------
# -- Curriculum Learning Experiment
# -------------------------------------------------------------------------------------------------

# TODO: review implementation
# class CurriculumCARLAEnvironment(SynchronousCARLAEnvironment):
#
#     def learn(self, agent: Agent, initial_timesteps: int, difficulty=1, increment=5, num_stages=1, max_timesteps=1024,
#               trials_per_stage=5, max_repetitions=1, save_agent=True, load_agent=False, agent_name='carla-agent'):
#         initial_difficulty = difficulty
#         target_difficulty = initial_difficulty + num_stages * increment
#
#         if load_agent:
#             agent.load(directory='weights/agents', filename=agent_name, environment=self)
#             print('Agent loaded.')
#
#         for difficulty in range(initial_difficulty, target_difficulty + 1, increment):
#             for r in range(max_repetitions):
#                 success_rate, avg_reward = self.stage(agent,
#                                                       trials=trials_per_stage,
#                                                       difficulty=difficulty,
#                                                       max_timesteps=min(initial_timesteps * difficulty, max_timesteps))
#
#                 print(f'[D-{difficulty}] success_rate: {round(success_rate, 2)}, avg_reward: {round(avg_reward, 2)}')
#
#                 if save_agent:
#                     agent.save(directory='weights/agents', filename=agent_name)
#                     print(f'[D-{difficulty}] Agent saved.')
#
#                 print(f'Repetition {r}-D-{difficulty} ended.')
#
#     def stage(self, agent: Agent, trials: int, difficulty: int, max_timesteps: int):
#         assert trials > 0
#         assert difficulty > 0
#         assert max_timesteps > 0
#
#         # self.reset(soft=False, route_size=difficulty)
#         avg_reward = 0.0
#         success_count = 0
#
#         for trial in range(trials):
#             # states = self.reset(soft=trial != 0, route_size=difficulty)
#             states = self.reset(route_size=difficulty)
#             trial_reward = 0.0
#
#             with self.synchronous_context:
#                 for t in range(max_timesteps):
#                     actions = agent.act(states)
#                     states, terminal, reward = self.execute(actions, distance_threshold=3.0)
#
#                     trial_reward += reward
#                     terminal = terminal or (t == max_timesteps - 1)
#
#                     if self.is_at_destination():
#                         agent.observe(reward, terminal=True)
#                         success_count += 1
#                         print(f'[T-{trial}] Successful -> reward: {round(trial_reward, 2)}')
#                         break
#
#                     elif terminal:
#                         agent.observe(reward, terminal=True)
#                         print(f'[T-{trial}] not successful -> reward: {round(trial_reward, 2)}')
#                         break
#                     else:
#                         agent.observe(reward, terminal=False)
#
#             avg_reward += trial_reward
#
#         return success_count / trials, avg_reward / trials
#
#     def is_at_destination(self, distance_threshold=2.0):
#         return self.route.distance_to_destination() < distance_threshold
#
#     def _get_observation(self, image):
#         if image is None:
#             image = np.zeros(shape=self.image_shape, dtype=np.uint8)
#
#         if image.shape != self.image_shape:
#             image = env_utils.resize(image, size=self.image_size)
#
#         return dict(image=image / 255.0,
#                     vehicle_features=self._get_vehicle_features(),
#                     road_features=self._get_road_features(),
#                     previous_actions=self.prev_actions)
