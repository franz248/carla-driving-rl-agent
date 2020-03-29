"""A list of classes that wraps specifications dict for the ease of defining TensorforceAgents agents"""


class Objectives:
    """Specifications of TensorForce's objectives"""

    @staticmethod
    def deterministic_policy_gradient():
        return dict(type='det_policy_gradient')

    @staticmethod
    def plus(objective1: dict, objective2: dict):
        return dict(type='plus',
                    objective1=objective1,
                    objective2=objective2)

    @staticmethod
    def policy_gradient(ratio_based=False, clipping_value=0.0, early_reduce=True):
        return dict(type='policy_gradient',
                    ratio_based=ratio_based,
                    clipping_value=clipping_value,
                    early_reduce=early_reduce)

    @staticmethod
    def value(value='state', huber_loss=0.0, early_reduce=True):
        return dict(type='value',
                    value=value,
                    huber_loss=huber_loss,
                    early_reduce=early_reduce)


class Optimizers:
    """Specifications of TensorForce's optimizers."""

    @staticmethod
    def clipping_step(optimizer: dict, threshold: float, mode='global_norm'):
        return dict(type='clipping_step',
                    optimizer=optimizer,
                    threshold=threshold,
                    mode=mode)

    @staticmethod
    def evolutionary(learning_rate: float, num_samples=1, unroll_loop=False):
        return dict(type='evolutionary',
                    learning_rate=learning_rate,
                    num_samples=num_samples,
                    unroll_loop=unroll_loop)

    @staticmethod
    def multi_step(optimizer: dict, num_steps: int, unroll_loop=False):
        return dict(type='multi_step',
                    optimizer=optimizer,
                    num_steps=num_steps,
                    unroll_loop=unroll_loop)

    @staticmethod
    def natural_gradient(learning_rate: float, cg_max_iterations=10, cg_damping=0.001, cg_unroll_loop=False):
        return dict(type='natural_gradient',
                    learning_rate=learning_rate,
                    cg_max_iterations=cg_max_iterations,
                    cg_damping=cg_damping,
                    cg_unroll_loop=cg_unroll_loop)

    @staticmethod
    def optimizing_step(optimizer: dict, ls_max_iterations=10, ls_accept_ratio=0.9, ls_mode='exponential',
                        ls_parameter=0.5, ls_unroll_loop=False):
        return dict(type='optimizing_step',
                    optimizer=optimizer,
                    ls_max_iterations=ls_max_iterations,
                    ls_accept_ratio=ls_accept_ratio,
                    ls_mode=ls_mode,
                    ls_parameter=ls_parameter,
                    ls_unroll_loop=ls_unroll_loop)

    @staticmethod
    def plus(optimizer1: dict, optimizer2: dict):
        return dict(type='plus',
                    optimizer1=optimizer1,
                    optimizer2=optimizer2)

    @staticmethod
    def subsampling_step(optimizer: dict, fraction: float):
        return dict(type='subsampling_step',
                    optimizer=optimizer,
                    fraction=fraction)


class Networks:
    @staticmethod
    def auto(size=64, depth=2, final_size=None, final_depth=1, internal_rnn=False):
        return dict(type='auto',
                    size=size,
                    depth=depth,
                    final_size=final_size,
                    final_depth=final_depth,
                    internal_rnn=internal_rnn)

    @staticmethod
    def convolutional(inputs: [str] = None, output: str = None, initial_filters=32, kernel=(3, 3), pool='max',
                      activation='relu', stride=1, dilation=1, dropout=0.0, layers=2, normalization='instance'):
        network = []

        if inputs is not None:
            if isinstance(inputs, list) and len(inputs) > 0:
                network.append(dict(type='retrieve', tensors=inputs))
            elif isinstance(inputs, str):
                network.append(dict(type='retrieve', tensors=[inputs]))

        # network.append(dict(type='image', height=60, width=60, grayscale=True))
        # network.append(dict(type='image', grayscale=True))

        for i in range(1, layers + 1):
            filters = initial_filters * i

            if stride > 1:
                convolution = dict(type='conv2d', size=filters, window=kernel, stride=stride, activation=activation,
                                   dropout=dropout)
            else:
                convolution = dict(type='conv2d', size=filters, window=kernel, dilation=dilation, activation=activation,
                                   dropout=dropout)

            network.append(convolution)

            if normalization == 'instance':
                network.append(dict(type='instance_normalization'))
            elif normalization == 'exponential' or normalization == 'exp':
                network.append(dict(type='exponential_normalization'))

            if pool is not None:
                network.append(dict(type='pool2d', reduction=pool))

        network.append(dict(type='pooling', reduction='mean'))

        if output is not None:
            network.append(dict(type='register', tensor=output))

        return network

    @staticmethod
    def dense(inputs: [str] = None, output: str = None, units=64, layers=2, activation='relu', dropout=0.0,
              normalization='instance'):
        network = []

        if inputs is not None:
            if isinstance(inputs, list) and len(inputs) > 0:
                network.append(dict(type='retrieve', tensors=inputs))
            elif isinstance(inputs, str):
                network.append(dict(type='retrieve', tensors=[inputs]))

        for i in range(layers):
            network.append(dict(type='dense', size=units, activation=activation, dropout=dropout))

            if normalization == 'instance':
                network.append(dict(type='instance_normalization'))
            elif normalization == 'exponential' or normalization == 'exp':
                network.append(dict(type='exponential_normalization'))

        if output is not None:
            network.append(dict(type='register', tensor=output))

        return network

    @staticmethod
    def complex(networks: [[dict]], layers=2, units=64, activation='relu', dropout=0.0, aggregation='concat'):
        network = networks
        outputs = []

        # find register (output) layers
        for net in networks:
            layer = net[-1]
            assert layer['type'] == 'register'

            outputs.append(layer['tensor'])

        # aggregate them
        network.append(dict(type='retrieve', tensors=outputs, aggregation=aggregation))

        for i in range(layers):
            network.append(dict(type='dense', size=units, activation=activation, dropout=dropout))

        return network


class Agents:
    pass


class Specifications:
    """Explicits TensorForce's specifications as dicts"""
    objectives = Objectives
    optimizers = Optimizers
    networks = Networks
    agents = Agents

    # Short names:
    obj = objectives
    opt = optimizers
    net = networks

    @staticmethod
    def update(unit: str, batch_size: int, frequency=None, start: int = None):
        return dict(unit=unit,
                    batch_size=batch_size,
                    frequency=frequency if frequency else batch_size,
                    start=start if start else batch_size)

    @staticmethod
    def reward_estimation(horizon: int, discount=1.0, estimate_horizon=False, estimate_actions=False,
                          estimate_advantage=False):
        return dict(horizon=horizon,
                    discount=discount,
                    estimate_horizon=estimate_horizon,
                    estimate_actions=estimate_actions,
                    estimate_advantage=estimate_advantage)

    @staticmethod
    def policy(network: dict, distributions: str = None, temperature=0.0, infer_states_value=False):
        return dict(type='parametrized_distributions',
                    infer_states_value=infer_states_value,
                    distributions=dict(type=distributions) if isinstance(distributions, str) else None,
                    network=network,
                    temperature=temperature)

    @staticmethod
    def agent_network():
        # TODO: embedd actions, and features before dense layers??
        # TODO: add RNN
        # TODO: image-ratio preserving convolutional kernels, e.g. (3, 2) or (2, 3) instead of (3, 3)
        # TODO: image stack 4-images (i.e. concat depth)?? or stack last-4 states and actions?

        return Networks.complex(networks=[
            Networks.convolutional(inputs='image', layers=5-2, stride=2, pool=None, dropout=0.2,
                                   output='image_out'),
            Networks.dense(inputs='vehicle_features', layers=2, units=32, dropout=0.2,
                           output='vehicle_out'),
            Networks.dense(inputs='road_features', layers=2, units=24, dropout=0.2,
                           output='road_out'),
            Networks.dense(inputs='previous_actions', layers=2, units=16, dropout=0.2,
                           output='actions_out')],
            layers=2,
            units=256)

    @staticmethod
    def agent_light_network():
        return Networks.complex(networks=[
            Networks.convolutional(inputs='image', layers=1, initial_filters=3, stride=32, pool='max', output='image_out'),
            Networks.dense(inputs='vehicle_features', layers=1, units=1, output='vehicle_out'),
            Networks.dense(inputs='road_features', layers=1, units=1, output='road_out'),
            Networks.dense(inputs='previous_actions', layers=1, units=1, output='actions_out')],
            layers=1,
            units=1)

    @staticmethod
    def saver():
        raise NotImplementedError

    @staticmethod
    def summarizer():
        raise NotImplementedError