'''This file is used to set up the Merkle Tree on the server side'''
from merkle import Node, MerkleTree, _check_proof, check_proof, print_tree, fetch_children_hash, get_num_leaves
from hashlib import sha256
from flask import Flask, request, jsonify
from collections import OrderedDict
import codecs, string, random, bisect, sqlite3, os.path
import cPickle as pickle
app = Flask(__name__)

# Uncomment to disable logging
# import logging
# log = logging.getLogger('werkzeug')
# log.setLevel(logging.ERROR)

hash_function = sha256
utxos = []

merkle_forest = OrderedDict()

top_root = None
top_merkle = None

def find_ge(my_array, target):
    '''Find smallest item greater-than or equal to key.
    Raise ValueError if no such item exists.
    If multiple keys are equal, return the leftmost.

    '''
    fst, snd = zip(*my_array)
    i = bisect.bisect_left(snd, target)
    if i == len(snd):
        raise ValueError('No item found with key at or above: %r' % (target,))
    return my_array[i], i

def find_nearest_above(my_array, target):
    '''A linear version of the find greater or equal to
    It is better to use find_ge instead
    '''
    return min(filter(lambda y: y >= target,my_array))

def read_in_blocks(database_name):
    '''Read in the blocks from the database containing all the RingCT outputs
    It will be in the format of a list of tuples
    If there already exists an pickle file, then don't bother reading from the database again
    '''
    if os.path.isfile("/data/"+database_name+".p"):
        fetched = pickle.load(open("/data/"+database_name+".p","rb"))
    else:
        conn = sqlite3.connect("/data/"+database_name+".db")
        c_1 = conn.cursor()
        c_1.execute('''SELECT block_hash, tx_hash, outkey, idx FROM out_table ORDER BY idx LIMIT 200''')
        fetched = c_1.fetchall()
        pickle.dump(fetched, open("/data/"+database_name+".p", "wb" ))
        conn.close()
    global utxos
    utxos = fetched
    
def block_to_merkle(block_outkeys):
    '''Takes in the outkeys that all belong to the same block (by block hash, we can also do height)
    and then builds a Merkle Tree. It also updates the client side block_root_hash dictionary
    and the server side block_merkle dictionary
    '''
    # change to 
    # for block_hash, tx_hash, outkey, idx in block_outkeys
    block_merkle_leaves=[]
    block_hash = block_outkeys[0][0]
    assert all(bhash == block_hash for bhash, _, _, _ in block_outkeys)

    while block_outkeys:
        curr_tx_hash = block_outkeys[0][1]
        tx_outkeys = []
        while block_outkeys[0][1] == curr_tx_hash:
            tx_outkeys.append(block_outkeys.pop(0))
            if not block_outkeys:
                break
        block_merkle_leaves.append(tx_to_merkle(tx_outkeys))
    block_merkle = MerkleTree(leaves=block_merkle_leaves)
    block_merkle.build()

    merkle_forest[codecs.encode(block_merkle.root.val, 'hex_codec')] = block_merkle
    return (codecs.encode(block_merkle.root.val, 'hex_codec'), block_merkle.root.idx)

def tx_to_merkle(tx_outkeys):
    '''Takes in the outkeys that all belong to the same transaction (by transaction hash) and builds
    a Merkle Tree. It also updates the client side tx_root_hash dictionary and the server side
    tx_dict dictionary'''
    tx_hash = tx_outkeys[0][1]
    assert all(t_hash == tx_hash for _, t_hash, _, _ in tx_outkeys)

    tx_merkle_leaves = [(outkey,idx) for _,_,outkey,idx in tx_outkeys]
    tx_merkle = MerkleTree(leaves=tx_merkle_leaves)
    tx_merkle.build()

    merkle_forest[codecs.encode(tx_merkle.root.val, 'hex_codec')] = tx_merkle
    return (codecs.encode(tx_merkle.root.val, 'hex_codec'), tx_merkle.root.idx)

def scan_over_new_blocks(new_blocks):
    '''Scan over the utxos, distinguishing new blocks
    We will use block hash to distinguish new blocks. The top Merkle Tree is created
    The client side top_root will be udpated, as well as the top_merkle ADS on the server'''
    top_merkle_leaves=[]
    while new_blocks:
        curr_block_hash = new_blocks[0][0]
        block_outkeys = []
        while new_blocks[0][0] == curr_block_hash:
            block_outkeys.append(new_blocks.pop(0))
            if not new_blocks:
                break
        top_merkle_leaves.append(block_to_merkle(block_outkeys))
    global top_merkle
    top_merkle = MerkleTree(leaves = top_merkle_leaves)
    top_merkle.build()

    global top_root
    top_root = (codecs.encode(top_merkle.root.val, 'hex_codec'), top_merkle.root.idx)
    merkle_forest[codecs.encode(top_merkle.root.val, 'hex_codec')] = top_merkle
    # merkle_forest.close()

def check_path(found_output, path_proof):
    '''This function, which is stored and run by the client, will check the Merkle proof returned
    by the server. The proof involves the following steps:
        1-  The requested output key is hashed to verify it matches the first part of the outkey proof.
        2-  The tx_merkle proof check is run.
        3-  The root of the first Merkle is hashed to verify it matches the first part of the tx proof.
        4-  The blk_merkle proof check is run.
        5-  The root of the second Merkle is hashed to verify it matches the first part of the blk proof.
        6-  The top_merkle proof is run.
        7-  Finally, the last part of the proof, which should contain the top merkle root, is verified.
    If all steps pass, then we have successfully checked that our query was returned correctly.
    If any of the checks fail, then the query was not returned correctly, and we need to run the verifier.'''
    outproof, txproof, blkproof = path_proof
    leaf_hashed, _ = outproof[0]
    if (hash_function(found_output[0]).hexdigest(),found_output[1]) == leaf_hashed:
        if check_proof(outproof):
            tx_hashed, _ = txproof[0]
            outproof_merkle_root, _ = outproof[-1]
            if (hash_function(outproof_merkle_root[0]).hexdigest(),outproof_merkle_root[1])==tx_hashed:
                if check_proof(txproof):
                    blk_hashed, _ = blkproof[0]
                    txproof_merkle_root, _ = txproof[-1]
                    if (hash_function(txproof_merkle_root[0]).hexdigest(), txproof_merkle_root[1]) == blk_hashed:
                        if check_proof(blkproof):
                            blkproof_merkle_root,_ = blkproof[-1]
                            if blkproof_merkle_root == top_root:
                                return True
    return False

def update_test():
    '''Updates the Merkle Tree by calling the function add_adjust. It will return the new
    root of the new top Merkle tree. This is used by profiling function only!'''
    if utxos:
        del merkle_forest[top_root[0]]
        curr_block_hash = utxos[0][0]
        block_outkeys = []
        while utxos[0][0] == curr_block_hash:
            block_outkeys.append(utxos.pop(0))
            if not utxos:
                break
        top_merkle.add_adjust(block_to_merkle(block_outkeys))
        global top_root
        top_root = (codecs.encode(top_merkle.root.val, 'hex_codec'), top_merkle.root.idx)
        merkle_forest[codecs.encode(top_merkle.root.val, 'hex_codec')] = top_merkle
    
@app.route("/getroot", methods = ["GET"])
def getroot():
    '''This function returns the root of the top merkle tree, when requested by the client.
    Whenever the top Merkle tree structure is updated, the function is also invoked.'''
    tr = {"root":top_root}
    return jsonify(tr)

@app.route("/getout", methods = ["GET"])
def getoutput():
    '''This function will return the output and proof associated with the requested index.
    It does this by first finding the block with the smallest global index greater than the 
    requested index. Next, it will find the transaction with the smallest global index greater 
    than the requested index. Afterwards, we will find the index, and return the data. To make sure
    we did this step correctly, we also keep track of the Merkle proofs along the way, and return
    them to the client as a tuple for them to check'''
    t = request.get_json()
    req_gidx = t["idx"]
    if req_gidx < 0 or req_gidx > top_root[1]:
    	return jsonify({"Failure": 0})
    else:
	    found_block, blk_idx = find_ge([(leaf.data, leaf.idx) for leaf in top_merkle.leaves], req_gidx)
	    blk_proof = top_merkle.get_proof(blk_idx)
	    block_merkle = merkle_forest[found_block[0]]

	    found_tx, tx_idx = find_ge([(leaf.data,leaf.idx) for leaf in block_merkle.leaves], req_gidx)
	    tx_proof = block_merkle.get_proof(tx_idx)
	    tx_merkle = merkle_forest[found_tx[0]]

	    found_output, output_idx = find_ge([(leaf.data,leaf.idx) for leaf in tx_merkle.leaves], req_gidx)
	    out_proof = tx_merkle.get_proof(output_idx)

	    path_proof = (out_proof,tx_proof,blk_proof)
	    return jsonify({"found":found_output, "proof":path_proof})

@app.route("/getouts", methods = ["GET"])
def getoutputs():
    '''Similar to get output, but retreives multiple outputs with one request'''
    t = request.get_json()
    req_gidxs = t["idx"]
    query_results = []
    for req_gidx in req_gidxs:
        if req_gidx < 0 or req_gidx > top_root[1]:
            return jsonify({"Failure": 0})
        else:
            found_block, blk_idx = find_ge([(leaf.data, leaf.idx) for leaf in top_merkle.leaves], req_gidx)
            blk_proof = top_merkle.get_proof(blk_idx)
            block_merkle = merkle_forest[found_block[0]]

            found_tx, tx_idx = find_ge([(leaf.data,leaf.idx) for leaf in block_merkle.leaves], req_gidx)
            tx_proof = block_merkle.get_proof(tx_idx)
            tx_merkle = merkle_forest[found_tx[0]]

            found_output, output_idx = find_ge([(leaf.data,leaf.idx) for leaf in tx_merkle.leaves], req_gidx)
            out_proof = tx_merkle.get_proof(output_idx)

            path_proof = (out_proof,tx_proof,blk_proof)
            query_results.append({"found":found_output, "proof":path_proof})
    return jsonify(results=query_results)

@app.route("/getchildren", methods = ["GET"])
def getchildren():
    '''Calls the get children Merkle Tree function. If there is no "root" argument passed in,
    we will get the children of the top root.'''
    t = request.get_json()
    if "root" in t:
        root = str(t["root"])
    else:
        root = top_root[0]
    path = t["path"]
    data = fetch_children_hash(merkle_forest[root], path=path)
    return jsonify({"data": data})

@app.route("/getnumleaves", methods = ["GET"])
def getleaves():
    '''Returns the number of leaves in a given root. If the root is invalid, we will return a failure.'''
    t = request.get_json()
    root = str(t["root"])
    if root in merkle_forest:
        data = get_num_leaves(merkle_forest[root])
        return jsonify({"data": data})
    else:
        return jsonify({"Failure": 0})

@app.route("/update", methods = ["POST"])
def update_merkle():
    '''Updates the Merkle Tree by calling the function add_adjust. It will return the new
    root of the new top Merkle tree.'''
    if utxos:
        del merkle_forest[top_root[0]]
        curr_block_hash = utxos[0][0]
        block_outkeys = []
        while utxos[0][0] == curr_block_hash:
            block_outkeys.append(utxos.pop(0))
            if not utxos:
                break
        top_merkle.add_adjust(block_to_merkle(block_outkeys))
        global top_root
        top_root = (codecs.encode(top_merkle.root.val, 'hex_codec'), top_merkle.root.idx)
        merkle_forest[codecs.encode(top_merkle.root.val, 'hex_codec')] = top_merkle
        return getroot()
    else:
        return jsonify({"Failure": 0})

def main():
    read_in_blocks("rct_output_10_23_2017")
    scan_over_new_blocks(utxos)
    read_in_blocks("rct_output_11_05_2017")

if __name__ == '__main__':
    main()
    # Run on localhost
    app.run() # use this for testing
    # app.run(host='0.0.0.0')
