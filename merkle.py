#   Modifed to keep track of the greatest index in each successive parent node
#   A Merkle proof is returned based on the index that is queried
#   For an odd number of leaves, we need to change the merkle tree to hash 
#   with itself instead
#   Question that remains is: Are the leaves global indices or transactions????

from hashlib import sha256
from math import log
import codecs

hash_function = sha256


class MerkleError(Exception):
    pass


class Node(object):
    """Each node has, as attributes, references to left (l) and right (r) child nodes, parent (p),
    and sibling (sib) node. It can also be aware of whether it is on the left or right hand side (side).
    data is hashed automatically by default, but does not have to be, if prehashed param is set to True.
    """
    # The leaf node in here can be the block, and whatever is inside are the output keys generated
    __slots__ = ['l', 'r', 'p', 'sib', 'side', 'val', 'idx', 'data']

    def __init__(self, data, prehashed=False, isleaf=False, ):
        if prehashed:
            # this can be anything, val will be the hash
            self.val = data[0] 
        else:
            self.val = hash_function(data[0]).digest()

        # if it is a leaf, we need to keep track of the data in the leaf, which will be the hash
        if isleaf:
            self.data = data[0]
        else:
            self.data = None
        self.idx = data[1]
        self.l = None
        self.r = None
        self.p = None
        self.sib = None
        self.side = None

    def __repr__(self):
        return "Val: <" + str(codecs.encode(self.val, 'hex_codec')) + ">"

class MerkleTree(object):
    """A Merkle tree implementation.  Added values are stored in a list until the tree is built.
    A list of data elements for Node values can be optionally supplied to the constructor.
    Data supplied to the constructor is hashed by default, but this can be overridden by
    providing prehashed=True in which case, node values should be hex encoded.
    """
    def __init__(self, leaves=[], prehashed=False, raw_digests=False):
        if prehashed and raw_digests:
            self.leaves = [Node(leaf, prehashed=True, isleaf=True) for leaf in leaves]
        elif prehashed:
            self.leaves = [Node(codecs.decode(leaf, 'hex_codec'), prehashed=True, isleaf=True) for leaf in leaves]
        else:
            self.leaves = [Node(leaf, isleaf=True) for leaf in leaves]
        self.root = None

    def __eq__(self, obj):
        return (self.root.val == obj.root.val) and (self.__class__ == obj.__class__)

    def add(self, data):
        """Add a Node to the tree, providing data, which is hashed automatically.
        """
        self.leaves.append(Node(data))

    def add_hash(self, value):
        """Add a Node based on a precomputed, hex encoded, hash value.
        """
        self.leaves.append(Node(((codecs.decode(value[0][0], 'hex_codec'),value[0][1]),value[1]), prehashed=True))

    def clear(self):
        """Clears the Merkle Tree by releasing the Merkle root and each leaf's references, the rest
        should be garbage collected.  This may be useful for situations where you want to take an existing
        tree, make changes to the leaves, but leave it uncalculated for some time, without node
        references that are no longer correct still hanging around. Usually it is better just to make
        a new tree.
        """
        self.root = None
        for leaf in self.leaves:
            leaf.p, leaf.sib, leaf.side = (None, ) * 3

    def build(self):
        """Calculate the merkle root and make references between nodes in the tree.
        """
        if not self.leaves:
            raise MerkleError('The tree has no leaves and cannot be calculated.')
        layer = self.leaves[::]
        while len(layer) != 1:
            layer = self._build(layer)
        self.root = layer[0]
        return self.root.val

    def _build(self, leaves):
        """Private helper function to create the next aggregation level and put all references in place.
        """
        new, odd = [], None
        # check if even number of leaves, promote odd leaf to next level, if not
        if len(leaves) % 2 == 1:
            odd = leaves.pop(-1)
        for i in range(0, len(leaves), 2):
            newnode = Node((leaves[i].val + leaves[i + 1].val, max(leaves[i].idx, leaves[i+1].idx)))
            newnode.l, newnode.r = leaves[i], leaves[i + 1]
            leaves[i].side, leaves[i + 1].side, leaves[i].p, leaves[i + 1].p = 'L', 'R', newnode, newnode
            leaves[i].sib, leaves[i + 1].sib = leaves[i + 1], leaves[i]
            new.append(newnode)
        if odd:
            #   for the node that is the odd one out, we will hash it with each other
            #   EDIT: Taken out, the odd will just be passed along
            # oddnode = Node((odd.val + odd.val, odd.idx))
            # oddnode.l = oddnode.r = odd
            # odd.p = oddnode
            # odd.sib = odd
            # odd.side = 'L'  #   doesn't matter what you assign it to, we will use right for convention
            # new.append(oddnode)
            new.append(odd)
        return new

    def _get_proof(self, index):
        """Assemble and return the chain leading from a given node to the merkle root of this tree.
        """
        chain = []
        this = self.leaves[index]
        chain.append(((this.val, this.idx), 'SELF'))
        while this.p:
            chain.append(((this.sib.val, this.sib.idx), this.sib.side))
            this = this.p
        chain.append(((this.val,this.idx), 'ROOT'))
        return chain

    def _get_all_proofs(self):
        """Assemble and return a list of all chains for all leaf nodes to the merkle root.
        """
        return [self._get_proof(i) for i in range(len(self.leaves))]

    def get_proof(self, index):
        """Assemble and return the chain leading from a given node to the merkle root of this tree
        with hash values in hex form
        """
        return [((codecs.encode(i[0][0], 'hex_codec'), i[0][1]), i[1]) for i in self._get_proof(index)]

    def get_all_proofs(self):
        """Assemble and return a list of all chains for all nodes to the merkle root, hex encoded.
        """
        return [[((codecs.encode(i[0][0], 'hex_codec'), i[0][1]), i[1]) for i in j] for j in self._get_all_proofs()]

    def _get_whole_subtrees(self):
        """Returns an array of nodes in the tree that have balanced subtrees beneath them,
        moving from left to right.
        """
        subtrees = []
        loose_leaves = len(self.leaves) - 2**int(log(len(self.leaves), 2))
        the_node = self.root
        while loose_leaves:
            subtrees.append(the_node.l)
            the_node = the_node.r
            loose_leaves = loose_leaves - 2**int(log(loose_leaves, 2))
        subtrees.append(the_node)
        return subtrees

    def add_adjust(self, data, prehashed=False):
        """Add a new leaf, and adjust the tree, without rebuilding the whole thing.
        """
        subtrees = self._get_whole_subtrees()
        new_node = Node(data, prehashed=prehashed, isleaf=True)
        self.leaves.append(new_node)
        for node in reversed(subtrees):
            new_parent = Node( (node.val + new_node.val , max(node.idx, new_node.idx)))
            node.p, new_node.p = new_parent, new_parent
            new_parent.l, new_parent.r = node, new_node
            node.sib, new_node.sib = new_node, node
            node.side, new_node.side = 'L', 'R'
            new_node = new_node.p
        self.root = new_node

def _check_proof(chain):
    """Verify a merkle chain to see if the Merkle root can be reproduced.
    """
    link = chain[0][0]
    for i in range(1, len(chain) - 1):
        if chain[i][1] == 'R':
            link = hash_function(link + chain[i][0]).digest()
        elif chain[i][1] == 'L':
            link = hash_function(chain[i][0] + link).digest()
        else:
            raise MerkleError('Link %s has no side value: %s' % (str(i), str(codecs.encode(chain[i][0], 'hex_codec'))))
    if link == chain[-1][0]:
        return link
    else:
        raise MerkleError('The Merkle Chain is not valid.')


def check_proof(chain):
    """Verify a merkle chain, with hashes hex encoded, to see if the Merkle root can be reproduced.
    """
    return codecs.encode(_check_proof([(codecs.decode(i[0][0], 'hex_codec'), i[1]) for i in chain]), 'hex_codec')


def join_chains(low, high):
    """Join two hierarchical merkle chains in the case where the root of a lower tree is an input
    to a higher level tree. The resulting chain should check out using the check functions. Use on either
    hex or binary chains.
    """
    if not low[-1][0] == high[0][0]:
        raise MerkleError('The two chains do not connect.')
    return low[:-1] + high[1:]

def print_tree(m):
    if isinstance(m, MerkleTree):
        print_tree_helper(m.root, level=0)
    else:
        raise TypeError("Input must be a MerkleTree object!")

#   for printing the tree
def print_tree_helper(root, level=0):
    print '\t' * level + str((codecs.encode(root.val, 'hex_codec'), root.idx))
    children = []
    children.extend((root.l, root.r))
    children = [x for x in children if x is not None]
    for child in children:
        assert child != None
        print_tree_helper(child, level=level+1)

def get_num_leaves(m):
    if isinstance(m, MerkleTree):
        return len(m.leaves)
    else:
        raise TypeError("Input must be a MerkleTree object!")


def fetch_children_hash(m, path=[]):
    """When a client makes a call, we will return the hashes of the left and right children of
    the tree, following the path provided. If none provided, just return the two subtree nodes
    of the top of the tree"""
    the_node = m.root
    if get_num_leaves(m) == 1:
        lhash=rhash=codecs.encode(the_node.val, 'hex_codec')
        ldata=rdata=the_node.data
    else: 
        for direction in path:
            assert direction in ['l','r']
            left_child = the_node.l
            right_child = the_node.r
            if left_child == right_child == None:
                break
            if direction == 'l':
                the_node = left_child
            else:
                the_node = right_child
        lc = the_node.l
        rc = the_node.r
        if lc:
            lhash = codecs.encode(lc.val, 'hex_codec')
            ldata = lc.data if lc.data else None
        else:
            lhash = None
            ldata = None
        if rc:
            rhash = codecs.encode(rc.val, 'hex_codec')
            rdata = rc.data if rc.data else None
        else:
            rhash = None
            rdata = None
    return (lhash, rhash, ldata, rdata) 