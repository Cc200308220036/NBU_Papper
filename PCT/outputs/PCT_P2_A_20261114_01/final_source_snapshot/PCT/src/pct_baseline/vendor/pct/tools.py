def init(module, weight_init, bias_init, gain=1):
    weight_init(module.weight.data, gain=gain)
    bias_init(module.bias.data)
    return module


def observation_decode_leaf_node(observation, internal_node_holder, internal_node_length, leaf_node_holder):
    internal_nodes = observation[:, 0:internal_node_holder, 0:internal_node_length]
    leaf_nodes = observation[:, internal_node_holder:internal_node_holder + leaf_node_holder, 0:8]
    current_box = observation[:,internal_node_holder + leaf_node_holder:, 0:6]
    valid_flag = observation[:,internal_node_holder: internal_node_holder + leaf_node_holder, 8]
    full_mask = observation[:, :, -1]
    return internal_nodes, leaf_nodes, current_box, valid_flag, full_mask


