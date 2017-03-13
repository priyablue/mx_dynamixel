# -*- coding: utf-8 -*-
#
# Software License Agreement (BSD License)
#
# Copyright (c) 2010-2011, Antons Rebguns.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of University of Arizona nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from __future__ import division


__author__ = 'Max Svetlik'
__copyright__ = 'Copyright (c) 2017 Max Svetlik, 2010-2011 Antons Rebguns'
__credits__ = 'Cara Slutter'

__license__ = 'BSD'
__maintainer__ = 'Max Svetlik'
__email__ = 'max@svenzva.com'


import rospy

from mx_driver.dynamixel_const import *
from mx_controllers.joint_controller import JointController

from mx_msgs.msg import JointState

class JointPositionControllerDual(JointController):
    def __init__(self, dxl_io, controller_namespace, port_namespace):
        JointController.__init__(self, dxl_io, controller_namespace, port_namespace)

        self.master_id = rospy.get_param(self.controller_namespace + '/motor_master/id')
        self.master_initial_position_raw = rospy.get_param(self.controller_namespace + '/motor_master/init')
        self.master_min_angle_raw = rospy.get_param(self.controller_namespace + '/motor_master/min')
        self.master_max_angle_raw = rospy.get_param(self.controller_namespace + '/motor_master/max')

        self.slave_id = rospy.get_param(self.controller_namespace + '/motor_slave/id')
        self.slave_offset = rospy.get_param(self.controller_namespace + '/motor_slave/calibration_offset', 0)

        self.flipped = self.master_min_angle_raw > self.master_max_angle_raw

        self.joint_state = JointState(name=self.joint_name, motor_ids=[self.master_id, self.slave_id])

    def initialize(self):
        # verify that the expected motor is connected and responding
        available_ids = rospy.get_param('dynamixel/%s/connected_ids' % self.port_namespace, [])
        if not (self.master_id in available_ids and
                self.slave_id in available_ids):
            rospy.logwarn('The specified motor id is not connected and responding.')
            rospy.logwarn('Available ids: %s' % str(available_ids))
            rospy.logwarn('Specified ids: %d %d' % (self.master_id, self.slave_id))
            return False

        self.RADIANS_PER_ENCODER_TICK = rospy.get_param('dynamixel/%s/%d/radians_per_encoder_tick' % (self.port_namespace, self.master_id))
        self.ENCODER_TICKS_PER_RADIAN = rospy.get_param('dynamixel/%s/%d/encoder_ticks_per_radian' % (self.port_namespace, self.master_id))

        if self.flipped:
            self.master_min_angle = (self.master_initial_position_raw - self.master_min_angle_raw) * self.RADIANS_PER_ENCODER_TICK
            self.master_max_angle = (self.master_initial_position_raw - self.master_max_angle_raw) * self.RADIANS_PER_ENCODER_TICK
        else:
            self.master_min_angle = (self.master_min_angle_raw - self.master_initial_position_raw) * self.RADIANS_PER_ENCODER_TICK
            self.master_max_angle = (self.master_max_angle_raw - self.master_initial_position_raw) * self.RADIANS_PER_ENCODER_TICK

        self.ENCODER_RESOLUTION = rospy.get_param('dynamixel/%s/%d/encoder_resolution' % (self.port_namespace, self.master_id))
        self.MAX_POSITION = self.ENCODER_RESOLUTION - 1
        self.VELOCITY_PER_TICK = rospy.get_param('dynamixel/%s/%d/radians_second_per_encoder_tick' % (self.port_namespace, self.master_id))
        self.MAX_VELOCITY = rospy.get_param('dynamixel/%s/%d/max_velocity' % (self.port_namespace, self.master_id))
        self.MIN_VELOCITY = self.VELOCITY_PER_TICK

        if self.torque_limit is not None: self.set_torque_limit(self.torque_limit)

        self.joint_max_speed = rospy.get_param(self.controller_namespace + '/joint_max_speed', self.MAX_VELOCITY)

        if self.joint_max_speed < self.MIN_VELOCITY: self.joint_max_speed = self.MIN_VELOCITY
        elif self.joint_max_speed > self.MAX_VELOCITY: self.joint_max_speed = self.MAX_VELOCITY

        if self.joint_speed < self.MIN_VELOCITY: self.joint_speed = self.MIN_VELOCITY
        elif self.joint_speed > self.joint_max_speed: self.joint_speed = self.joint_max_speed

        self.set_speed(self.joint_speed)

        return True

    def pos_rad_to_raw(self, angle):
        if angle < self.master_min_angle:
            angle = self.master_min_angle
        elif angle > self.master_max_angle:
            angle = self.master_max_angle
        mcv_master = self.rad_to_raw(angle, self.master_initial_position_raw, self.flipped, self.ENCODER_TICKS_PER_RADIAN)
        mcv_slave = self.MAX_POSITION - mcv_master + self.slave_offset
        if mcv_slave < 0:
            mcv_slave = 0
        elif mcv_slave > self.MAX_POSITION:
            mcv_slave = self.MAX_POSITION
        return (mcv_master, mcv_slave)

    def spd_rad_to_raw(self, spd_rad):
        if spd_rad < self.MIN_VELOCITY:
            spd_rad = self.MIN_VELOCITY
        elif spd_rad > self.joint_max_speed:
            spd_rad = self.joint_max_speed
        # velocity of 0 means maximum, make sure that doesn't happen
        return max(1, int(round(spd_rad / self.VELOCITY_PER_TICK)))

    def set_torque_enable(self, torque_enable):
        mcv_master = (self.master_id, torque_enable)
        mcv_slave = (self.slave_id, torque_enable)
        self.dxl_io.set_multi_torque_enabled([mcv_master, mcv_slave])

    def set_speed(self, speed):
        if speed < self.MIN_VELOCITY: speed = self.MIN_VELOCITY
        elif speed > self.joint_max_speed: speed = self.joint_max_speed
        speed_raw = int(round(speed / self.VELOCITY_PER_TICK))
        mcv_master = (self.master_id, speed_raw if speed_raw > 0 else 1)
        mcv_slave = (self.slave_id, mcv_master[1])
        self.dxl_io.set_multi_speed([mcv_master, mcv_slave])

    def set_torque_limit(self, max_torque):
        if max_torque > 1: max_torque = 1.0
        elif max_torque < 0: max_torque = 0.0  # turn off motor torque
        raw_torque_val = int(MX_MAX_TORQUE_TICK * max_torque)
        mcv_master = (self.master_id, raw_torque_val)
        mcv_slave = (self.slave_id, raw_torque_val)
        self.dxl_io.set_multi_torque_limit([mcv_master, mcv_slave])

    def process_motor_states(self, state_list):
        if self.running:
            states = {}

            for state in state_list.motor_states:
                if state.id in [self.master_id, self.slave_id]: states[state.id] = state

            if self.master_id in states and self.slave_id in states:
                state = states[self.master_id]
                self.joint_state.motor_temps = [state.temperature, states[self.slave_id].temperature]
                self.joint_state.goal_pos = self.raw_to_rad(state.goal, self.master_initial_position_raw, self.flipped, self.RADIANS_PER_ENCODER_TICK)
                self.joint_state.current_pos = self.raw_to_rad(state.position, self.master_initial_position_raw, self.flipped, self.RADIANS_PER_ENCODER_TICK)
                self.joint_state.error = state.error * self.RADIANS_PER_ENCODER_TICK
                self.joint_state.velocity = state.speed * self.VELOCITY_PER_TICK
                self.joint_state.load = max(abs(state.load), abs(states[self.slave_id].load)) #state.load
                self.joint_state.is_moving = state.moving
                self.joint_state.header.stamp = rospy.Time.from_sec(state.timestamp)
                self.joint_state_pub.publish(self.joint_state)

    def process_command(self, msg):
        angle = msg.data
        if angle < self.master_min_angle: angle = self.master_min_angle
        elif angle > self.master_max_angle: angle = self.master_max_angle
        mcv_master = (self.master_id, self.rad_to_raw(angle, self.master_initial_position_raw, self.flipped, self.ENCODER_TICKS_PER_RADIAN))
        mcv_slave = [self.slave_id, self.MAX_POSITION - mcv_master[1] + self.slave_offset]
        if mcv_slave[1] < 0: mcv_slave[1] = 0
        elif mcv_slave[1] > self.MAX_POSITION: mcv_slave[1] = self.MAX_POSITION
        self.dxl_io.set_multi_position([mcv_master, mcv_slave])