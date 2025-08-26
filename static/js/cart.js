// Add product to cart
function addToCart(productId, quantity = null) {
    const qtyInput = document.getElementById(`qty-${productId}`);
    const qty = quantity || (qtyInput ? parseInt(qtyInput.value) : 1);

    if (qty < 1) {
        showNotification('Please select a valid quantity', 'error');
        return;
    }

    fetch('/add_to_cart', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            product_id: productId,
            quantity: qty
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Product added to cart!', 'success');
            updateCartCount();
            if (qtyInput) qtyInput.value = 1;
        } else {
            showNotification('Error adding product to cart', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error adding product to cart', 'error');
    });
}

// Update cart item quantity
function updateQuantity(productId, newQuantity) {
    if (newQuantity < 1) {
        removeFromCart(productId);
        return;
    }

    fetch('/update_cart', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            product_id: productId,
            quantity: newQuantity
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload(); // Reload to update totals
        } else {
            showNotification('Error updating cart', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error updating cart', 'error');
    });
}

// Remove item from cart
function removeFromCart(productId) {
    if (!confirm('Remove this item from cart?')) return;

    fetch('/remove_from_cart', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            product_id: productId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            document.querySelector(`[data-product-id="${productId}"]`).remove();
            showNotification('Item removed from cart', 'success');
            updateCartCount();
            location.reload();
        } else {
            showNotification('Error removing item', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error removing item', 'error');
    });
}

// Place order
function placeOrder() {
    const address = document.getElementById('deliveryAddress').value.trim();
    const phone = document.getElementById('phoneNumber').value.trim();

    if (!address) {
        showNotification('Please enter delivery address', 'error');
        return;
    }

    if (!validatePhone(phone)) {
        showNotification('Please enter a valid phone number', 'error');
        return;
    }

    fetch('/place_order', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            address: address,
            phone: phone
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Order placed successfully!', 'success');
            setTimeout(() => {
                window.location.href = `/orders`;
            }, 2000);
        } else {
            showNotification(data.message || 'Error placing order', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error placing order', 'error');
    });
}
